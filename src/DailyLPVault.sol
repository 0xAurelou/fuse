// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {ExactTransfer} from "./common/ExactTransfer.sol";

interface IDailyCustodyIdentity {
    function usdc() external view returns (IERC20);
    function lpVault() external view returns (address);
    function access() external view returns (AccessController);
}

interface IDailyBacking {
    function usdc() external view returns (IERC20);
    function lpVault() external view returns (address);
    function fundReserve(uint256 amount) external;
}

/// @notice Isolated release candidate, not wired into existing deployments.
/// Nontransferable capital lots retain each accepted bet's original owners.
/// Custody must physically lock stakes; every outcome settles USDC atomically.
/// Oracle truth and daily reward-demand inputs remain dual-attested by custody.
contract DailyLPVault is Module, EIP712, ReentrancyGuard {
    using ExactTransfer for IERC20;
    using SafeERC20 for IERC20;

    uint256 public constant MAX_LOTS = 64;
    uint256 public constant MAX_OPEN_BETS = 1024;
    uint256 public constant MAX_MONEY = 1e30;
    uint256 public constant DURATION = 30;

    struct Limits {
        uint256 perBet;
        uint256[3] perMarket;
        uint256 total;
        uint256 admissionBuffer;
        uint256 distributionBuffer;
        uint256 backingBuffer;
    }

    struct Lot {
        address owner;
        uint256 equity;
        uint256 reserved;
        int256 pnl;
        uint256 mark;
        bool exitRequested;
        bool archived;
    }

    struct Bet {
        // Oracle/canonical times use milliseconds, matching the shared Go engine.
        uint64 start;
        uint64 expiry;
        uint8 asset;
        uint8 status; // 0 absent, 1 open, 2 win, 3 loss, 4 void
        uint64 finalVoidAt;
        uint256 stake;
        uint256 liability;
        uint256[] lots;
        uint256[] allocations;
    }

    struct Close {
        uint256 eligible;
        uint256 processed;
        uint256 fee;
        uint256 backing;
        bool feePaid;
        bool backingPaid;
    }

    struct DepositAuthorization {
        address owner;
        uint256 amount;
        bytes32 id;
        uint64 deadline;
    }
    bytes32 public constant DEPOSIT_TYPEHASH = keccak256(
        "DepositAuthorization(address owner,uint256 amount,bytes32 id,uint64 deadline,uint256 signatureVersion)"
    );

    IERC20 public immutable usdc;
    address public immutable operator;
    bytes32 public immutable limitsHash;
    Limits public limits;
    address public custody;
    IDailyBacking public reserve;
    uint64 public currentDay;
    uint256 public sequence;
    uint256 public betSequence;
    bool public depositWindow = true;
    uint256 public nextLot = 1;
    uint256 public accountedCash;
    uint256 public totalEquity;
    uint256 public openExposure;
    uint256 public openStakeProfit;
    uint256[3] public marketExposure;
    uint256 public operatorDue;
    uint256 public backingDue;
    uint256 public totalContributed;
    uint256 public totalExited;
    int256 public totalRealized;
    uint256 public totalFees;
    uint256 public totalBacking;
    mapping(uint256 => Lot) public lots;
    mapping(bytes32 => Bet) private _bets;
    mapping(uint64 => Close) public closes;
    mapping(bytes32 => bool) public usedDepositAuthorizations;
    uint256[] private _activeLots;
    mapping(uint256 => uint256) private _lotPosition;
    bytes32[] private _openBets;
    mapping(bytes32 => uint256) private _betPosition;

    error InvalidAction();
    error CloseRequired();
    error InsufficientCapital();
    event CapitalDeposited(uint256 indexed lot, address indexed owner, uint256 amount);
    event CapitalWithdrawn(uint256 indexed lot, address indexed owner, uint256 amount);
    event ExitPreference(uint256 indexed lot, bool requested);
    event LotArchived(uint256 indexed lot);
    event BetReserved(bytes32 indexed id, uint8 indexed asset, uint256 stake, uint256 liability);
    event OutcomeRecorded(bytes32 indexed id, uint8 outcome, uint64 canonicalTime, int256 lpPnL);
    event FinalVoidQueued(bytes32 indexed id, uint64 canonicalTime);
    event DailyClosed(uint64 indexed day, uint256 eligible, uint256 processed, uint256 fee, uint256 backing);
    event CloseTransferPaid(uint64 indexed day, bool backing, uint256 amount);

    constructor(AccessController access_, IERC20 usdc_, address operator_, Limits memory limits_)
        Module(access_)
        EIP712("FUSE DailyLPVault", "1")
    {
        if (
            address(usdc_).code.length == 0 || operator_ == address(0) || operator_ == address(this)
                || limits_.perBet == 0 || limits_.perBet > limits_.total || limits_.total > MAX_MONEY
                || limits_.admissionBuffer > limits_.distributionBuffer
                || limits_.distributionBuffer > limits_.backingBuffer || limits_.backingBuffer > MAX_MONEY
        ) {
            revert InvalidConfiguration();
        }
        for (uint256 i; i < 3; ++i) {
            if (limits_.perMarket[i] == 0 || limits_.perMarket[i] > limits_.total) revert InvalidConfiguration();
        }
        usdc = usdc_;
        operator = operator_;
        limits = limits_;
        limitsHash = keccak256(abi.encode(limits_));
        currentDay = uint64(block.timestamp / 1 days);
    }

    function configure(IDailyCustodyIdentity custody_, IDailyBacking reserve_) external onlyGovernance {
        if (
            custody != address(0) || address(custody_).code.length == 0 || address(reserve_).code.length == 0
                || address(custody_) == address(reserve_) || operator == address(custody_)
                || operator == address(reserve_) || custody_.lpVault() != address(this) || custody_.usdc() != usdc
                || custody_.access() != access || reserve_.lpVault() != address(this) || reserve_.usdc() != usdc
        ) revert InvalidConfiguration();
        custody = address(custody_);
        reserve = reserve_;
    }

    modifier onlyCustody() {
        if (msg.sender != custody) revert Unauthorized();
        _;
    }

    function cutoff() public view returns (uint256) {
        return (uint256(currentDay) + 1) * 1 days;
    }

    function availableCash() public view returns (uint256) {
        return accountedCash - operatorDue - backingDue;
    }

    function activeLots() external view returns (uint256[] memory) {
        return _activeLots;
    }

    function openBetIds() external view returns (bytes32[] memory) {
        return _openBets;
    }

    function bet(bytes32 id) external view returns (Bet memory) {
        return _bets[id];
    }

    function pendingProfit(uint256 id) public view returns (uint256) {
        Lot storage lot = lots[id];
        return lot.pnl > 0 && uint256(lot.pnl) > lot.mark ? uint256(lot.pnl) - lot.mark : 0;
    }

    function maxWithdrawal(uint256 id) public view returns (uint256) {
        Lot storage lot = lots[id];
        uint256 retained = lot.reserved + pendingProfit(id);
        uint256 own = lot.equity > retained ? lot.equity - retained : 0;
        // Admission headroom finances future bets, not an obligation owed by LPs.
        uint256 cash = availableCash();
        uint256 room = cash > openExposure ? cash - openExposure : 0;
        return Math.min(own, room);
    }

    function hashDeposit(DepositAuthorization calldata a) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(DEPOSIT_TYPEHASH, a, access.signatureVersion())));
    }

    /// @notice Bounded slots require explicit capacity authorization, not wallet caps.
    function deposit(DepositAuthorization calldata a, bytes calldata settlementSig, bytes calldata riskSig)
        external
        nonReentrant
        returns (uint256 id)
    {
        uint256 amount = a.amount;
        if (
            custody == address(0) || !access.tradingPaused() || !depositWindow || openExposure != 0
                || block.timestamp >= cutoff() || amount == 0 || amount > MAX_MONEY - totalEquity
                || _activeLots.length == MAX_LOTS || a.owner != msg.sender || a.id == bytes32(0)
                || usedDepositAuthorizations[a.id] || a.deadline < block.timestamp
                || a.deadline > block.timestamp + 1 hours
        ) revert InvalidAction();
        bytes32 digest = hashDeposit(a);
        access.verify(access.SETTLEMENT_SIGNER(), digest, settlementSig);
        access.verify(access.RISK_SIGNER(), digest, riskSig);
        usedDepositAuthorizations[a.id] = true;
        usdc.pull(msg.sender, amount);
        id = nextLot++;
        lots[id] = Lot(msg.sender, amount, 0, 0, 0, false, false);
        _activeLots.push(id);
        _lotPosition[id] = _activeLots.length;
        accountedCash += amount;
        totalEquity += amount;
        totalContributed += amount;
        ++sequence;
        _checkCash();
        emit CapitalDeposited(id, msg.sender, amount);
    }

    function requestExit(uint256 id, bool requested) external {
        Lot storage lot = lots[id];
        if (lot.owner != msg.sender || lot.archived) revert Unauthorized();
        lot.exitRequested = requested;
        ++sequence;
        emit ExitPreference(id, requested);
    }

    function withdraw(uint256 id, uint256 amount) external nonReentrant {
        Lot storage lot = lots[id];
        if (lot.owner != msg.sender || lot.archived) revert Unauthorized();
        if (amount == 0 || amount > maxWithdrawal(id)) revert InsufficientCapital();
        lot.equity -= amount;
        totalEquity -= amount;
        accountedCash -= amount;
        totalExited += amount;
        ++sequence;
        if (lot.equity == 0) _archive(id);
        usdc.push(msg.sender, amount);
        _checkCash();
        emit CapitalWithdrawn(id, msg.sender, amount);
    }

    /// @notice Anyone may free a slot for an economically empty account.
    function archiveEmptyLot(uint256 id) external {
        if (
            lots[id].owner == address(0) || lots[id].archived || lots[id].equity != 0 || lots[id].reserved != 0
                || pendingProfit(id) != 0
        ) revert InvalidAction();
        _archive(id);
        ++sequence;
    }

    function accept(bytes32 id, uint8 asset, uint256 stake, uint256 multiplier)
        external
        onlyCustody
        nonReentrant
        whenTradingActive
    {
        if (block.timestamp >= cutoff()) revert CloseRequired();
        if (
            id == bytes32(0) || _bets[id].status != 0 || asset >= 3 || stake == 0 || !_payout(multiplier)
                || stake > MAX_MONEY / multiplier || _openBets.length == MAX_OPEN_BETS
        ) revert InvalidAction();
        uint256 liability = stake * (multiplier - 1);
        Limits memory caps = limits;
        if (
            liability > caps.perBet || openExposure + liability > caps.total
                || marketExposure[asset] + liability > caps.perMarket[asset]
                || stake > MAX_MONEY - totalEquity - openStakeProfit
                || openExposure + liability + caps.admissionBuffer > availableCash()
        ) revert InsufficientCapital();
        uint256[] memory weights = new uint256[](_activeLots.length);
        uint256 capacity;
        for (uint256 i; i < weights.length; ++i) {
            Lot storage lot = lots[_activeLots[i]];
            weights[i] = lot.exitRequested ? 0 : lot.equity - lot.reserved;
            capacity += weights[i];
        }
        if (capacity < liability) revert InsufficientCapital();
        uint256[] memory allocation = _split(liability, weights, _activeLots);
        Bet storage b = _bets[id];
        b.start = uint64(block.timestamp * 1000);
        b.expiry = uint64((block.timestamp + DURATION) * 1000);
        b.asset = asset;
        b.status = 1;
        b.stake = stake;
        b.liability = liability;
        for (uint256 i; i < allocation.length; ++i) {
            if (allocation[i] == 0) continue;
            uint256 lotId = _activeLots[i];
            lots[lotId].reserved += allocation[i];
            b.lots.push(lotId);
            b.allocations.push(allocation[i]);
        }
        openExposure += liability;
        openStakeProfit += stake;
        marketExposure[asset] += liability;
        _openBets.push(id);
        _betPosition[id] = _openBets.length;
        depositWindow = false;
        ++betSequence;
        ++sequence;
        _checkCash();
        emit BetReserved(id, asset, stake, liability);
    }

    /// @dev Loss stake must already be in this vault. Wins pay fixed custody.
    /// No recognized winner can remain in LP equity awaiting a customer claim.
    function resolve(bytes32 id, uint8 outcome, uint64 canonicalTime) external onlyCustody nonReentrant {
        int256 pnl = _recordOutcome(id, outcome, canonicalTime);
        if (pnl < 0) usdc.push(custody, uint256(-pnl));
        _checkCash();
    }

    /// @notice Journal batches keep per-bet ownership and move only net USDC.
    function resolveBatch(bytes32[] calldata ids, uint8[] calldata outcomes, uint64[] calldata canonicalTimes)
        external
        onlyCustody
        nonReentrant
    {
        if (ids.length == 0 || ids.length > 16 || outcomes.length != ids.length || canonicalTimes.length != ids.length) revert InvalidAction();
        int256 net;
        for (uint256 i; i < ids.length; ++i) {
            net += _recordOutcome(ids[i], outcomes[i], canonicalTimes[i]);
        }
        if (net < 0) usdc.push(custody, uint256(-net));
        _checkCash();
    }

    function _recordOutcome(bytes32 id, uint8 outcome, uint64 canonicalTime) private returns (int256 pnl) {
        Bet storage b = _bets[id];
        if (
            b.status != 1 || outcome < 2 || outcome > 4 || canonicalTime < b.start
                || canonicalTime > block.timestamp * 1000 || canonicalTime < uint256(currentDay) * 1 days * 1000
                || canonicalTime >= cutoff() * 1000 || (outcome == 2 && canonicalTime != b.expiry)
                || (outcome == 3 && canonicalTime >= b.expiry) || (outcome == 4 && canonicalTime < b.expiry)
                || (b.finalVoidAt != 0 && (outcome != 4 || canonicalTime != b.finalVoidAt))
        ) {
            revert InvalidAction();
        }
        uint256 amount = outcome == 2 ? b.liability : outcome == 3 ? b.stake : 0;
        uint256[] memory split = _split(amount, b.allocations, b.lots);
        for (uint256 i; i < b.lots.length; ++i) {
            Lot storage lot = lots[b.lots[i]];
            lot.reserved -= b.allocations[i];
            if (outcome == 2) {
                lot.equity -= split[i];
                lot.pnl -= int256(split[i]);
            } else if (outcome == 3) {
                lot.equity += split[i];
                lot.pnl += int256(split[i]);
            }
        }
        b.status = outcome;
        openExposure -= b.liability;
        openStakeProfit -= b.stake;
        marketExposure[b.asset] -= b.liability;
        uint256 pos = _betPosition[id] - 1;
        bytes32 last = _openBets[_openBets.length - 1];
        _openBets[pos] = last;
        _betPosition[last] = pos + 1;
        _openBets.pop();
        delete _betPosition[id];
        if (outcome == 2) {
            pnl = -int256(amount);
            accountedCash -= amount;
            totalEquity -= amount;
        } else if (outcome == 3) {
            pnl = int256(amount);
            if (amount > MAX_MONEY - totalEquity) revert InsufficientCapital();
            accountedCash += amount;
            totalEquity += amount;
        }
        totalRealized += pnl;
        depositWindow = false;
        ++betSequence;
        ++sequence;
        emit OutcomeRecorded(id, outcome, canonicalTime, pnl);
    }

    /// @notice Authenticate a final void determined in a later accounting day.
    /// Keep both the original accepted risk and customer stake locked until that
    /// day; preceding closes can advance without inventing an earlier outcome.
    function queueFinalVoid(bytes32 id, uint64 canonicalTime) external onlyCustody nonReentrant {
        Bet storage b = _bets[id];
        if (
            b.status != 1 || b.finalVoidAt != 0 || canonicalTime < b.expiry || canonicalTime < cutoff() * 1000
                || canonicalTime > block.timestamp * 1000
        ) revert InvalidAction();
        b.finalVoidAt = canonicalTime;
        depositWindow = false;
        ++betSequence;
        ++sequence;
        emit FinalVoidQueued(id, canonicalTime);
    }

    function closeDay(uint64 watermark, uint256 allowance, uint256 pendingCredit, uint256 standardNeed30d)
        external
        onlyCustody
        nonReentrant
    {
        if (
            block.timestamp < cutoff() || watermark < cutoff() * 1000 || watermark > block.timestamp * 1000
                || allowance > MAX_MONEY || pendingCredit > MAX_MONEY || standardNeed30d > MAX_MONEY
        ) {
            revert InvalidAction();
        }
        for (uint256 i; i < _openBets.length; ++i) {
            Bet storage open = _bets[_openBets[i]];
            if (open.expiry < cutoff() * 1000 && open.finalVoidAt < cutoff() * 1000) revert InvalidAction();
        }
        uint256[] memory weights = new uint256[](_activeLots.length);
        uint256 eligible;
        uint256 capacity;
        for (uint256 i; i < weights.length; ++i) {
            uint256 id = _activeLots[i];
            uint256 profit = pendingProfit(id);
            eligible += profit;
            weights[i] = Math.min(profit, lots[id].equity - lots[id].reserved);
            capacity += weights[i];
        }
        uint256 free = availableCash() - openExposure;
        uint256 room = free > limits.distributionBuffer ? free - limits.distributionBuffer : 0;
        uint256 processed = Math.min(capacity, room);
        uint256 fee = Math.mulDiv(processed, 500, 10_000);
        uint256 target = standardNeed30d * 2; // ceil(60 * demand / 30)
        uint256 credit = allowance + pendingCredit;
        uint256 need = target > credit ? Math.mulDiv(target - credit, 10_000, 9000, Math.Rounding.Ceil) : 0;
        uint256 afterFee = free - fee;
        uint256 backingRoom = afterFee > limits.backingBuffer ? afterFee - limits.backingBuffer : 0;
        uint256 backing = Math.min(processed - fee, Math.min(need, backingRoom));
        uint256[] memory consumed = _split(processed, weights, _activeLots);
        uint256[] memory charges = _split(fee + backing, consumed, _activeLots);
        for (uint256 i; i < weights.length; ++i) {
            Lot storage lot = lots[_activeLots[i]];
            lot.mark += consumed[i];
            lot.equity -= charges[i];
        }
        totalEquity -= fee + backing;
        operatorDue += fee;
        backingDue += backing;
        totalFees += fee;
        totalBacking += backing;
        closes[currentDay] = Close(eligible, processed, fee, backing, false, false);
        emit DailyClosed(currentDay, eligible, processed, fee, backing);
        ++currentDay;
        ++sequence;
        depositWindow = true;
        _checkCash();
    }

    function payFee(uint64 day) external nonReentrant {
        Close storage row = closes[day];
        if (day >= currentDay || row.feePaid || row.fee == 0) revert InvalidAction();
        row.feePaid = true;
        operatorDue -= row.fee;
        accountedCash -= row.fee;
        ++sequence;
        usdc.push(operator, row.fee);
        _checkCash();
        emit CloseTransferPaid(day, false, row.fee);
    }

    function payBacking(uint64 day) external nonReentrant {
        Close storage row = closes[day];
        if (day >= currentDay || row.backingPaid || row.backing == 0) revert InvalidAction();
        row.backingPaid = true;
        backingDue -= row.backing;
        accountedCash -= row.backing;
        ++sequence;
        uint256 beforeCash = usdc.balanceOf(address(this));
        uint256 beforeReserve = usdc.balanceOf(address(reserve));
        usdc.forceApprove(address(reserve), row.backing);
        reserve.fundReserve(row.backing);
        usdc.forceApprove(address(reserve), 0);
        if (
            usdc.balanceOf(address(this)) != beforeCash - row.backing
                || usdc.balanceOf(address(reserve)) != beforeReserve + row.backing
        ) revert InvalidAction();
        _checkCash();
        emit CloseTransferPaid(day, true, row.backing);
    }

    function _archive(uint256 id) private {
        uint256 pos = _lotPosition[id] - 1;
        uint256 last = _activeLots[_activeLots.length - 1];
        _activeLots[pos] = last;
        _lotPosition[last] = pos + 1;
        _activeLots.pop();
        delete _lotPosition[id];
        lots[id].archived = true;
        emit LotArchived(id);
    }

    function _split(uint256 amount, uint256[] memory weights, uint256[] memory ids)
        private
        pure
        returns (uint256[] memory parts)
    {
        parts = new uint256[](weights.length);
        if (amount == 0) return parts;
        uint256 total;
        for (uint256 i; i < weights.length; ++i) {
            total += weights[i];
        }
        if (total == 0) revert InsufficientCapital();
        uint256 assigned;
        uint256[] memory remainder = new uint256[](weights.length);
        for (uint256 i; i < weights.length; ++i) {
            parts[i] = Math.mulDiv(amount, weights[i], total);
            assigned += parts[i];
            remainder[i] = mulmod(amount, weights[i], total);
        }
        bool[] memory used = new bool[](weights.length);
        for (uint256 n = amount - assigned; n != 0; --n) {
            uint256 best = type(uint256).max;
            for (uint256 i; i < weights.length; ++i) {
                if (used[i] || weights[i] == 0) continue;
                if (
                    best == type(uint256).max || remainder[i] > remainder[best]
                        || (remainder[i] == remainder[best] && ids[i] < ids[best])
                ) best = i;
            }
            ++parts[best];
            used[best] = true;
        }
    }

    function _checkCash() private view {
        assert(availableCash() == totalEquity);
        assert(totalEquity >= openExposure);
        assert(totalEquity + openStakeProfit <= MAX_MONEY);
        if (usdc.balanceOf(address(this)) < accountedCash) revert InsufficientCapital();
    }

    function _payout(uint256 m) private pure returns (bool) {
        return m == 2 || m == 5 || m == 10 || m == 25 || m == 50 || m == 100 || m == 250 || m == 1000 || m == 10000;
    }
}
