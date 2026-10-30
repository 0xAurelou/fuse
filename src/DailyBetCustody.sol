// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {ExactTransfer} from "./common/ExactTransfer.sol";
import {DailyLPVault} from "./DailyLPVault.sol";

/// @notice Isolated onchain custody adapter for the daily LP candidate.
/// Dual signatures attest quotes, oracle outcomes and daily input completeness;
/// this contract does not independently verify prices or promised FUSE rewards.
contract DailyBetCustody is Module, EIP712, ReentrancyGuard {
    using ExactTransfer for IERC20;

    struct Quote {
        bytes32 id;
        address account;
        uint8 asset;
        uint256 stake;
        uint256 multiplier;
        uint256 lower;
        uint256 referencePrice;
        uint256 upper;
        uint64 quotedAt;
        uint64 validUntil;
        bytes32 pricingHash;
    }

    struct Outcome {
        bytes32 id;
        uint8 outcome; // 2 win, 3 loss, 4 void
        uint64 canonicalTime; // milliseconds; deadlines/quote freshness use seconds
        bytes32 evidenceHash;
        uint64 deadline;
    }

    struct DailyClose {
        uint64 day;
        uint64 watermark; // milliseconds, covering the UTC close boundary
        uint256 betSequence;
        uint256 allowance;
        uint256 pendingCredit;
        uint256 standardNeed30d;
        bytes32 journalHash;
        uint64 deadline;
    }

    struct Ticket {
        address account;
        uint256 stake;
        uint256 multiplier;
        bytes32 termsHash;
        bool resolved;
        uint64 finalVoidAt;
    }
    bytes32 public constant QUOTE_TYPEHASH = keccak256(
        "Quote(bytes32 id,address account,uint8 asset,uint256 stake,uint256 multiplier,uint256 lower,uint256 referencePrice,uint256 upper,uint64 quotedAt,uint64 validUntil,bytes32 pricingHash,bytes32 limitsHash,uint256 signatureVersion)"
    );
    bytes32 public constant OUTCOME_TYPEHASH = keccak256(
        "Outcome(bytes32 id,uint8 outcome,uint64 canonicalTime,bytes32 evidenceHash,uint64 deadline,uint256 signatureVersion)"
    );
    bytes32 public constant CLOSE_TYPEHASH = keccak256(
        "DailyClose(uint64 day,uint64 watermark,uint256 betSequence,uint256 allowance,uint256 pendingCredit,uint256 standardNeed30d,bytes32 journalHash,uint64 deadline,uint256 signatureVersion)"
    );
    bytes32 public constant BATCH_TYPEHASH =
        keccak256("SettlementBatch(bytes32 outcomesHash,bytes32 journalHash,uint64 deadline,uint256 signatureVersion)");
    uint256 public constant MAX_QUOTE_AGE = 5;
    IERC20 public immutable usdc;
    DailyLPVault public immutable lpVault;
    uint256 public immutable maxAccountExposure;
    uint256 public immutable maxAccountActive;
    uint256 public totalAvailable;
    uint256 public totalLocked;
    uint256 public totalBonusReserved;
    mapping(address => uint256) public available;
    mapping(bytes32 => Ticket) public tickets;
    mapping(address => uint256) public accountExposure;
    mapping(address => uint256) public accountActive;

    error InvalidAuthorization();
    error InsufficientBalance();
    event CustomerDeposited(address indexed account, uint256 amount);
    event CustomerWithdrawn(address indexed account, uint256 amount);
    event TicketAccepted(bytes32 indexed id, address indexed account, bytes32 termsHash, uint64 start, uint64 expiry);
    event TicketResolved(bytes32 indexed id, uint8 outcome, uint64 canonicalTime, bytes32 evidenceHash);
    event BatchSettled(bytes32 indexed digest, bytes32 indexed journalHash, int256 lpNet, uint256 count);

    constructor(AccessController access_, IERC20 usdc_, DailyLPVault vault_, uint256 accountCap_, uint256 activeCap_)
        Module(access_)
        EIP712("FUSE DailyBetCustody", "1")
    {
        if (
            address(vault_).code.length == 0 || vault_.usdc() != usdc_ || vault_.access() != access_ || accountCap_ == 0
                || accountCap_ > vault_.MAX_MONEY() || activeCap_ == 0 || activeCap_ > vault_.MAX_OPEN_BETS()
        ) {
            revert InvalidConfiguration();
        }
        usdc = usdc_;
        lpVault = vault_;
        maxAccountExposure = accountCap_;
        maxAccountActive = activeCap_;
    }

    function hashQuote(Quote calldata q) public view returns (bytes32) {
        return
            _hashTypedDataV4(keccak256(abi.encode(QUOTE_TYPEHASH, q, lpVault.limitsHash(), access.signatureVersion())));
    }

    function hashOutcome(Outcome calldata o) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(OUTCOME_TYPEHASH, o, access.signatureVersion())));
    }

    function hashClose(DailyClose calldata c) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(CLOSE_TYPEHASH, c, access.signatureVersion())));
    }

    function hashBatch(Outcome[] calldata outcomes, bytes32 journalHash, uint64 deadline)
        public
        view
        returns (bytes32)
    {
        return _hashTypedDataV4(
            keccak256(
                abi.encode(
                    BATCH_TYPEHASH, keccak256(abi.encode(outcomes)), journalHash, deadline, access.signatureVersion()
                )
            )
        );
    }

    function deposit(uint256 amount) external nonReentrant {
        if (amount == 0 || amount > lpVault.MAX_MONEY() - totalAvailable - totalLocked - totalBonusReserved) {
            revert InsufficientBalance();
        }
        usdc.pull(msg.sender, amount);
        available[msg.sender] += amount;
        totalAvailable += amount;
        _checkCash();
        emit CustomerDeposited(msg.sender, amount);
    }

    /// @notice Funded customer money remains withdrawable during every pause.
    function withdraw(uint256 amount) external nonReentrant {
        if (amount == 0 || amount > available[msg.sender]) revert InsufficientBalance();
        available[msg.sender] -= amount;
        totalAvailable -= amount;
        usdc.push(msg.sender, amount);
        _checkCash();
        emit CustomerWithdrawn(msg.sender, amount);
    }

    function accept(Quote calldata q, bytes calldata settlementSig, bytes calldata riskSig)
        external
        nonReentrant
        whenTradingActive
    {
        if (
            q.account != msg.sender || q.id == bytes32(0) || tickets[q.id].account != address(0) || q.stake == 0
                || q.stake > available[msg.sender] || q.lower == 0 || q.lower >= q.referencePrice
                || q.referencePrice >= q.upper || q.pricingHash == bytes32(0) || q.quotedAt > block.timestamp
                || q.validUntil < block.timestamp || q.validUntil < q.quotedAt
                || q.validUntil - q.quotedAt > MAX_QUOTE_AGE
        ) {
            revert InvalidAuthorization();
        }
        bytes32 digest = hashQuote(q);
        _verify(digest, settlementSig, riskSig);
        available[msg.sender] -= q.stake;
        totalAvailable -= q.stake;
        totalLocked += q.stake;
        tickets[q.id] = Ticket(msg.sender, q.stake, q.multiplier, digest, false, 0);
        lpVault.accept(q.id, q.asset, q.stake, q.multiplier);
        uint256 exposure = accountExposure[msg.sender] + q.stake * (q.multiplier - 1);
        uint256 bonus = q.stake * (q.multiplier - 1);
        if (exposure > maxAccountExposure || accountActive[msg.sender] == maxAccountActive) {
            revert InsufficientBalance();
        }
        if (bonus > lpVault.MAX_MONEY() - totalAvailable - totalLocked - totalBonusReserved) {
            revert InsufficientBalance();
        }
        totalBonusReserved += bonus;
        accountExposure[msg.sender] = exposure;
        ++accountActive[msg.sender];
        _checkCash();
        emit TicketAccepted(
            q.id, msg.sender, digest, uint64(block.timestamp * 1000), uint64((block.timestamp + 30) * 1000)
        );
    }

    function resolve(Outcome calldata o, bytes calldata settlementSig, bytes calldata riskSig) external nonReentrant {
        Ticket storage ticket = tickets[o.id];
        if (
            ticket.account == address(0) || ticket.resolved || ticket.finalVoidAt != 0 || o.evidenceHash == bytes32(0)
                || o.deadline < block.timestamp || o.outcome < 2 || o.outcome > 4
        ) revert InvalidAuthorization();
        _verify(hashOutcome(o), settlementSig, riskSig);
        if (o.outcome == 4 && o.canonicalTime >= lpVault.cutoff() * 1000) {
            lpVault.queueFinalVoid(o.id, o.canonicalTime);
            ticket.finalVoidAt = o.canonicalTime;
            return;
        }
        _finish(o.id, o.outcome, o.canonicalTime, o.evidenceHash);
    }

    /// @notice Previously authenticated void rights survive signer rotation.
    function completeVoid(bytes32 id) external nonReentrant {
        Ticket storage ticket = tickets[id];
        if (ticket.finalVoidAt == 0 || ticket.resolved) revert InvalidAuthorization();
        _finish(id, 4, ticket.finalVoidAt, bytes32(0));
    }

    function _finish(bytes32 id, uint8 outcome, uint64 canonicalTime, bytes32 evidenceHash) private {
        Ticket storage ticket = tickets[id];
        _accountOutcome(ticket, outcome);
        // Loss cash cannot enter LP equity before its physical receipt.
        if (outcome == 3) usdc.push(address(lpVault), ticket.stake);
        lpVault.resolve(id, outcome, canonicalTime);
        _checkCash();
        emit TicketResolved(id, outcome, canonicalTime, evidenceHash);
    }

    /// @notice Same journal settlement shape as papertrade: one signed batch,
    /// per-bet accounting, and one net transfer between custody and LP cash.
    function settleBatch(
        Outcome[] calldata outcomes,
        bytes32 journalHash,
        uint64 deadline,
        bytes calldata settlementSig,
        bytes calldata riskSig
    ) external nonReentrant {
        if (outcomes.length == 0 || outcomes.length > 16 || journalHash == bytes32(0) || deadline < block.timestamp) revert InvalidAuthorization();
        bytes32 digest = hashBatch(outcomes, journalHash, deadline);
        _verify(digest, settlementSig, riskSig);
        int256 net = _settleBatch(outcomes);
        emit BatchSettled(digest, journalHash, net, outcomes.length);
    }

    function _settleBatch(Outcome[] calldata outcomes) private returns (int256 net) {
        bytes32[] memory ids = new bytes32[](outcomes.length);
        uint8[] memory statuses = new uint8[](outcomes.length);
        uint64[] memory times = new uint64[](outcomes.length);
        for (uint256 i; i < outcomes.length; ++i) {
            Outcome calldata o = outcomes[i];
            Ticket storage ticket = tickets[o.id];
            if (
                ticket.account == address(0) || ticket.resolved || ticket.finalVoidAt != 0
                    || o.evidenceHash == bytes32(0) || o.deadline < block.timestamp || o.outcome < 2 || o.outcome > 4
            ) revert InvalidAuthorization();
            _accountOutcome(ticket, o.outcome);
            net += o.outcome == 3
                ? int256(ticket.stake)
                : o.outcome == 2 ? -int256(ticket.stake * (ticket.multiplier - 1)) : int256(0);
            ids[i] = o.id;
            statuses[i] = o.outcome;
            times[i] = o.canonicalTime;
            emit TicketResolved(o.id, o.outcome, o.canonicalTime, o.evidenceHash);
        }
        if (net > 0) usdc.push(address(lpVault), uint256(net));
        lpVault.resolveBatch(ids, statuses, times);
        _checkCash();
    }

    function _accountOutcome(Ticket storage ticket, uint8 outcome) private {
        ticket.resolved = true;
        totalLocked -= ticket.stake;
        totalBonusReserved -= ticket.stake * (ticket.multiplier - 1);
        accountExposure[ticket.account] -= ticket.stake * (ticket.multiplier - 1);
        --accountActive[ticket.account];
        // The adapter's reentrancy lock prevents release before atomic funding.
        uint256 credit = outcome == 2 ? ticket.stake * ticket.multiplier : outcome == 4 ? ticket.stake : 0;
        available[ticket.account] += credit;
        totalAvailable += credit;
    }

    function closeDay(DailyClose calldata c, bytes calldata settlementSig, bytes calldata riskSig)
        external
        nonReentrant
    {
        if (
            c.day != lpVault.currentDay() || c.betSequence != lpVault.betSequence() || c.journalHash == bytes32(0)
                || c.deadline < block.timestamp
        ) revert InvalidAuthorization();
        _verify(hashClose(c), settlementSig, riskSig);
        lpVault.closeDay(c.watermark, c.allowance, c.pendingCredit, c.standardNeed30d);
    }

    function _verify(bytes32 digest, bytes calldata settlementSig, bytes calldata riskSig) private view {
        access.verify(access.SETTLEMENT_SIGNER(), digest, settlementSig);
        access.verify(access.RISK_SIGNER(), digest, riskSig);
    }

    function _checkCash() private view {
        assert(totalAvailable + totalLocked + totalBonusReserved <= lpVault.MAX_MONEY());
        if (usdc.balanceOf(address(this)) < totalAvailable + totalLocked) revert InsufficientBalance();
    }
}
