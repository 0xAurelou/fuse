#!/usr/bin/env python3
"""Export pinned compiled FUSE artifacts. Addresses must come from a reviewed deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import re

MODULES = ["AccessController", "CustomerCustodyVault", "LPVault", "SettlementController",
           "WithdrawalGateway", "FUSEToken", "RewardDistributor", "RedemptionReserve"]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addresses", type=Path, required=True, help="JSON object: module name -> deployed address")
    parser.add_argument("--chain-id", type=int, choices=[998, 999, 31337], required=True)
    parser.add_argument("--confirmations", type=int, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("out"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.confirmations <= 0:
        parser.error("confirmations must be explicitly positive")
    addresses = json.loads(args.addresses.read_text())
    modules = {}
    seen = set()
    for name in MODULES:
        address = addresses.get(name, "")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address) or int(address, 16) == 0 or address.lower() in seen:
            parser.error(f"missing, zero or duplicated {name} deployment address")
        seen.add(address.lower())
        artifact = args.artifacts / f"{name}.sol" / f"{name}.json"
        raw = artifact.read_bytes()
        compiled = json.loads(raw)
        if not compiled.get("abi") or not compiled.get("bytecode", {}).get("object"):
            parser.error(f"{artifact} is not a compiled deployable artifact")
        modules[name] = {"address": address, "version": "fuse-v0.1", "artifact": str(artifact.resolve()),
                         "sha256": hashlib.sha256(raw).hexdigest()}
    output = {"chain_id": args.chain_id, "confirmations": args.confirmations, "modules": modules}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")

if __name__ == "__main__":
    main()
