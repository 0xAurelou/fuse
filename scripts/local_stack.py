#!/usr/bin/env python3
"""Start or test FUSE's isolated Anvil + PostgreSQL + Go backend locally."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"


def run(args, *, cwd=ROOT, env=None, capture=False):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                            text=True, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise RuntimeError(f"{Path(str(args[0])).name} failed ({result.returncode}): {detail}")
    return result.stdout.strip() if capture else ""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_free(port):
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def process_ready(process, check, log):
    if process.poll() is not None:
        raise RuntimeError(f"service exited; inspect {log}")
    return check()


def wait_for(check, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("service did not become ready; inspect the local log files")


def http_ready(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=1) as response:
        return response.status == 200


def rpc_ready(url):
    request = urllib.request.Request(url, data=b'{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}',
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=1) as response:
        return json.load(response).get("result") == "0x7a69"


def read_rpc(url, method, params):
    request = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=15) as response:
        result = json.load(response)
    if result.get("error") or result.get("id") != 1 or result.get("result") is None:
        raise RuntimeError(f"read RPC {method} failed: {result.get('error')}")
    return result["result"]


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()
        return bool(state) and not state.startswith("Z")
    except ProcessLookupError:
        return False


class Stack:
    def __init__(self, directory, ephemeral=False):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.runtime_path = self.directory / "runtime.json"
        self.runtime = json.loads(self.runtime_path.read_text()) if self.runtime_path.exists() else {
            "rpc_port": int(os.environ.get("FUSE_LOCAL_RPC_PORT", free_port() if ephemeral else 8545)),
            "http_port": int(os.environ.get("FUSE_LOCAL_HTTP_PORT", free_port() if ephemeral else 8080)),
            "pg_port": int(os.environ.get("FUSE_LOCAL_PG_PORT", free_port() if ephemeral else 55432)),
            "admin_token": secrets.token_hex(32),
            "genesis_timestamp": int(time.time()),
            "pids": {},
        }
        self.env = dict(os.environ)
        self.go = os.environ.get("GO_BINARY", shutil.which("go") or "go")
        self.anvil = shutil.which("anvil") or "anvil"
        self.forge = shutil.which("forge") or "forge"
        self.pg = None
        self.binary = self.directory / "fuse-local"
        self.manifest = self.directory / "deployment.json"
        self.rpc = f'http://127.0.0.1:{self.runtime["rpc_port"]}'
        self.http = f'http://127.0.0.1:{self.runtime["http_port"]}'
        self.database = os.environ.get("FUSE_LOCAL_DATABASE_URL", self.runtime.get("database_url", ""))
        if not self.database:
            self.database = f'postgres://fuse@127.0.0.1:{self.runtime["pg_port"]}/fuse_local?sslmode=disable'
            self.runtime["owns_postgres"] = True
        self.runtime.update(rpc_url=self.rpc, http_url=self.http, database_url=self.database,
                            manifest=str(self.manifest), directory=str(self.directory))
        self.save()

    def save(self):
        self.runtime_path.write_text(json.dumps(self.runtime, indent=2) + "\n")
        self.runtime_path.chmod(0o600)

    def pg_bin(self):
        if self.pg is None:
            configured = os.environ.get("PGBIN")
            if configured:
                self.pg = Path(configured)
            else:
                self.pg = Path(run(["pg_config", "--bindir"], capture=True))
            if not (self.pg / "initdb").exists():
                raise RuntimeError("PostgreSQL server binaries unavailable; set PGBIN or FUSE_LOCAL_DATABASE_URL")
        return self.pg

    def spawn(self, name, args, env=None):
        with (self.directory / f"{name}.log").open("ab") as log:
            process = subprocess.Popen([str(a) for a in args], cwd=ENGINE, env=env or self.env,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       close_fds=True, start_new_session=True)
        self.runtime["pids"][name] = process.pid
        self.save()
        return process

    def up(self, serve=True, live=False, traders=100, hyperevm_fork=False):
        if alive(self.runtime["pids"].get("backend")):
            if serve:
                self.status()
                return
            raise RuntimeError("test stack already has a backend writer")
        print("Building local contracts and backend...", flush=True)
        run([self.forge, "build", "--offline", "--quiet"])
        run([self.go, "build", "-o", self.binary, "./cmd/fuse-local"], cwd=ENGINE, env=self.env)
        if not alive(self.runtime["pids"].get("anvil")):
            if not port_free(self.runtime["rpc_port"]):
                if os.environ.get("FUSE_LOCAL_RPC_PORT"):
                    raise RuntimeError("requested Anvil port is already in use")
                self.runtime["rpc_port"] = free_port()
                self.rpc = f'http://127.0.0.1:{self.runtime["rpc_port"]}'
                self.runtime["rpc_url"] = self.rpc
                self.save()
            source_args = ["--timestamp", str(self.runtime["genesis_timestamp"])]
            if hyperevm_fork:
                endpoint = "https://rpc.hyperliquid-testnet.xyz/evm"
                if int(read_rpc(endpoint, "eth_chainId", []), 16) != 998:
                    raise RuntimeError("official HyperEVM testnet chain mismatch")
                block = read_rpc(endpoint, "eth_getBlockByNumber", ["latest", False])
                fork = {"source_url": endpoint, "source_chain_id": 998,
                        "source_block": int(block["number"], 16), "source_hash": block["hash"],
                        "execution_chain_id": 31337, "public_transactions": False,
                        "scope": "Anvil fork compatibility; does not test HyperBFT inclusion or public deployment"}
                self.runtime["hyperevm_fork"] = fork
                (self.directory / "fork.json").write_text(json.dumps(fork, indent=2) + "\n")
                self.save()
                source_args = ["--fork-url", endpoint, "--fork-block-number", str(fork["source_block"]),
                               "--hardfork", "cancun", "--no-storage-caching", "--retries", "2", "--timeout", "15000"]
                print(f"Forking HyperEVM testnet block {fork['source_block']} into LOCAL chain 31337...", flush=True)
            anvil_process = self.spawn("anvil", [self.anvil, "--host", "127.0.0.1", "--port", self.runtime["rpc_port"],
                                 "--chain-id", "31337", *source_args,
                                 "--state", self.directory / "anvil-state.json", "--preserve-historical-states", "--silent"])
            wait_for(lambda: process_ready(anvil_process, lambda: rpc_ready(self.rpc), self.directory / "anvil.log"))
        else:
            wait_for(lambda: rpc_ready(self.rpc))
        if self.runtime.get("owns_postgres"):
            pg = self.pg_bin()
            data = self.directory / "postgres"
            if not (data / "PG_VERSION").exists():
                run([pg / "initdb", "-D", data, "-A", "trust", "-U", "fuse", "--no-locale", "-E", "UTF8"], capture=True)
            running = subprocess.run([str(pg / "pg_ctl"), "-D", str(data), "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if not running:
                if not port_free(self.runtime["pg_port"]):
                    if os.environ.get("FUSE_LOCAL_PG_PORT"):
                        raise RuntimeError("requested PostgreSQL port is already in use")
                    self.runtime["pg_port"] = free_port()
                    self.database = f'postgres://fuse@127.0.0.1:{self.runtime["pg_port"]}/fuse_local?sslmode=disable'
                    self.runtime["database_url"] = self.database
                    self.save()
                # A short Unix socket path also works with deep macOS checkout paths.
                socket_dir = Path(tempfile.mkdtemp(prefix="fuse-pg-socket-"))
                self.runtime["socket_dir"] = str(socket_dir)
                options = f'-h 127.0.0.1 -p {self.runtime["pg_port"]} -k {shlex.quote(str(socket_dir))}'
                run([pg / "pg_ctl", "-D", data, "-l", self.directory / "postgres.log", "-o", options, "start"], capture=True)
            present = run([pg / "psql", "-h", "127.0.0.1", "-p", self.runtime["pg_port"], "-U", "fuse", "-d", "postgres", "-tAc",
                           "SELECT 1 FROM pg_database WHERE datname='fuse_local'"], capture=True)
            if present != "1":
                run([pg / "createdb", "-h", "127.0.0.1", "-p", self.runtime["pg_port"], "-U", "fuse", "fuse_local"], capture=True)
        self.save()
        if not self.manifest.exists():
            print("Deploying and wiring real contracts on Anvil...", flush=True)
            run([self.binary, "deploy", "-rpc", self.rpc, "-manifest", self.manifest, "-artifacts", ROOT / "out", *(["-lp", "250000000000", "-traders", str(traders)] if live else [])], cwd=ENGINE, env=self.env, capture=True)
        if serve:
            env = dict(self.env, DATABASE_URL=self.database, FUSE_LOCAL_ADMIN_TOKEN=self.runtime["admin_token"])
            if not port_free(self.runtime["http_port"]):
                if os.environ.get("FUSE_LOCAL_HTTP_PORT"):
                    raise RuntimeError("requested backend port is already in use")
                self.runtime["http_port"] = free_port()
                self.http = f'http://127.0.0.1:{self.runtime["http_port"]}'
                self.runtime["http_url"] = self.http
                self.save()
            backend_process = self.spawn("backend", [self.binary, "serve", "-rpc", self.rpc, "-manifest", self.manifest,
                                   "-listen", f'127.0.0.1:{self.runtime["http_port"]}', "-config", ENGINE / "config/local.json"], env)
            wait_for(lambda: process_ready(backend_process, lambda: http_ready(self.http + "/healthz"), self.directory / "backend.log"))
            self.status()

    def stop_process(self, name, marker, sig):
        pid = self.runtime["pids"].get(name)
        if alive(pid):
            command = run(["ps", "-p", pid, "-o", "command="], capture=True)
            if marker not in command:
                raise RuntimeError(f"refusing to stop reused {name} PID {pid}")
            os.kill(pid, sig)
            deadline = time.monotonic() + 15
            while alive(pid) and time.monotonic() < deadline:
                # Child processes may be zombies until their owning process reaps them.
                state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], text=True, stdout=subprocess.PIPE).stdout.strip()
                if state.startswith("Z"):
                    break
                time.sleep(0.1)
            if alive(pid) and not state.startswith("Z"):
                raise RuntimeError(f"{name} did not stop cleanly; inspect logs")
        self.runtime["pids"].pop(name, None)
        self.save()

    def down(self):
        self.stop_process("backend", str(self.manifest), signal.SIGTERM)
        self.stop_process("anvil", str(self.directory / "anvil-state.json"), signal.SIGINT)
        if self.runtime.get("owns_postgres") and (self.directory / "postgres/PG_VERSION").exists():
            pg = self.pg_bin()
            if subprocess.run([str(pg / "pg_ctl"), "-D", str(self.directory / "postgres"), "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                run([pg / "pg_ctl", "-D", self.directory / "postgres", "stop", "-m", "fast"], capture=True)
        socket_dir = self.runtime.pop("socket_dir", None)
        if socket_dir and Path(socket_dir).name.startswith("fuse-pg-socket-"):
            shutil.rmtree(socket_dir, ignore_errors=True)
        self.save()

    def status(self):
        print(f"Backend: {self.http}\nAnvil:   {self.rpc}\nRuntime: {self.runtime_path}\nManifest: {self.manifest}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down", "status", "restart", "test", "live-test", "fork-test"])
    parser.add_argument("--directory", type=Path, default=Path(os.environ.get("FUSE_LOCAL_DIR", ROOT / ".local")))
    parser.add_argument("--traders", type=int, default=100, help="live users, 2..300; larger populations share the 100-user risk budget")
    parser.add_argument("--config", type=Path, default=ENGINE / "config/local.json", help="live engine policy")
    parser.add_argument("--seed", type=int, default=20261025, help="live strategy seed")
    parser.add_argument("--capture-seconds", type=int, default=0, help="minimum real-time oracle capture, 0..3600")
    parser.add_argument("--cohort-size", type=int, default=0, help="wallets per entry cohort; zero means one cohort")
    parser.add_argument("--cohort-interval-seconds", type=int, default=0, help="entry cohort spacing, 0..600")
    parser.add_argument("--control-every", type=int, default=0, help="every Nth wallet uses the exact frozen policy width")
    parser.add_argument("--calibration", type=Path, help="freeze this fitted candidate before deployment, then automatically validate the live run")
    args = parser.parse_args()
    if not 2 <= args.traders <= 300:
        parser.error("--traders must be 2..300")
    if not (0 <= args.capture_seconds <= 3600 and 0 <= args.cohort_size <= 300 and 0 <= args.cohort_interval_seconds <= 600 and (args.control_every == 0 or args.control_every >= 2)):
        parser.error("invalid capture, cohort or control arguments")
    if args.action == "live-test":
        # Evidence and isolated chain/database are retained after services stop.
        directory = ROOT / ".local" / "live-runs" / time.strftime("%Y%m%d-%H%M%S")
        if directory.exists():
            raise RuntimeError("live run directory already exists")
        stack = Stack(directory, ephemeral=True)
        try:
            config = args.config.resolve()
            if args.calibration:
                from validate_pricing import freeze_experiment
                freeze_experiment(args.calibration.resolve(), config, directory,
                                  {"traders": args.traders, "seed": args.seed, "capture_seconds": args.capture_seconds,
                                   "cohort_size": args.cohort_size, "cohort_interval_seconds": args.cohort_interval_seconds,
                                   "control_every": args.control_every})
                config = directory / "frozen-policy.json"
            stack.up(serve=False, live=True, traders=args.traders)
            env = dict(stack.env, DATABASE_URL=stack.database)
            run([stack.binary, "simulate", "-rpc", stack.rpc, "-manifest", stack.manifest,
                 "-config", config, "-output", directory / "evidence", "-traders", str(args.traders), "-seed", str(args.seed),
                 "-capture", f"{args.capture_seconds}s", "-cohort-size", str(args.cohort_size),
                 "-cohort-interval", f"{args.cohort_interval_seconds}s", "-control-every", str(args.control_every)], cwd=ENGINE, env=env)
            if args.calibration:
                run([sys.executable, ROOT / "scripts/validate_pricing.py", "--experiment", directory / "experiment.json", "--run", directory / "evidence"])
            run([sys.executable, ROOT / "scripts/analyze_papertrade.py"])
        finally:
            stack.down()
            print(f"Live E2E evidence retained at {directory}", flush=True)
        return
    if args.action in ("test", "fork-test"):
        is_fork = args.action == "fork-test"
        directory = ROOT / ".local" / "fork-runs" / time.strftime("%Y%m%d-%H%M%S") if is_fork else Path(tempfile.mkdtemp(prefix="fuse-e2e-"))
        stack = Stack(directory, ephemeral=True)
        succeeded = False
        try:
            stack.up(serve=False, hyperevm_fork=is_fork)
            env = dict(stack.env, FUSE_LOCAL_E2E_RPC=stack.rpc, FUSE_LOCAL_E2E_MANIFEST=str(stack.manifest), FUSE_LOCAL_E2E_DATABASE=stack.database)
            print("Running actual-contract + HTTP + PostgreSQL recovery E2E...", flush=True)
            if is_fork:
                transcript = run([stack.go, "test", "-race", "./internal/localdev", "-run", "TestLocalContractBackendE2E", "-count=1", "-v"], cwd=ENGINE, env=env, capture=True)
                (directory / "e2e.log").write_text(transcript + "\n")
                print(transcript, flush=True)
                (directory / "result.json").write_text(json.dumps({"passed": True, "fork": stack.runtime["hyperevm_fork"],
                    "coverage": ["deposits", "settlement in both directions", "withdrawals and replay rejection", "reward claims", "reserve funding", "token burn and redemption", "signer rotation", "restart recovery", "transient RPC outage admission fencing and recovery", "idle sync preserves journal", "finalized local reorg halt"]}, indent=2) + "\n")
            else:
                run([stack.go, "test", "-race", "./internal/localdev", "-run", "TestLocalContractBackendE2E", "-count=1", "-v"], cwd=ENGINE, env=env)
            succeeded = True
        finally:
            stack.down()
            if succeeded and not is_fork:
                shutil.rmtree(directory)
            else:
                print(f"E2E logs retained at {directory}", file=sys.stderr)
        return
    stack = Stack(args.directory)
    with (stack.directory / "manager.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == "up":
            stack.up()
        elif args.action == "down":
            stack.down()
        elif args.action == "restart":
            stack.stop_process("backend", str(stack.manifest), signal.SIGTERM)
            stack.up()
        else:
            stack.status()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Local stack: {error}", file=sys.stderr)
        sys.exit(1)
