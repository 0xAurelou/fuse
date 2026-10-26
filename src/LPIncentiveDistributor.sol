// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {FUSEToken} from "./FUSEToken.sol";
import {LPShareVault} from "./LPShareVault.sol";
import {EmissionEscrow} from "./AllocationEscrows.sol";

/// @notice Finite LP bootstrapping. Capital-time is onchain; actual underwriting
/// liability-time is independently attested by settlement and risk from the journal.
contract LPIncentiveDistributor is Module, EIP712, ReentrancyGuard {
    struct UtilizationReport {
        uint64 epoch;
        uint256 liabilitySeconds;
        bytes32 journalHash;
        uint256 deadline;
    }

    struct RewardEpoch {
        uint256 capitalSeconds;
        uint256 liabilitySeconds;
        uint256 budget;
        bytes32 journalHash;
        bool published;
    }

    struct AccountCursor {
        uint64 epoch;
        uint256 index;
    }
    bytes32 public constant REPORT_TYPEHASH = keccak256(
        "LPUtilizationReport(uint64 epoch,uint256 liabilitySeconds,bytes32 journalHash,uint256 deadline,uint256 signatureVersion)"
    );
    uint256 public constant BUDGET = 50_000_000 ether;
    uint64 public constant CAMPAIGN_DAYS = 90;
    uint256 public constant VESTING = 30 days;
    uint256 private constant SCALE = 1e27;
    LPShareVault public immutable vault;
    FUSEToken public immutable token;
    EmissionEscrow public immutable escrow;
    uint64 public start;
    uint64 public end;
    uint64 public lastUpdate;
    uint64 public latestEpoch;
    uint16 public targetUtilizationBps;
    uint256 public cumulativeIndex;
    uint256 public totalClaimed;
    uint256 public totalPublishedBudget;
    mapping(uint64 => uint256) public capitalSeconds;
    mapping(uint64 => uint256) public indexAtEnd;
    mapping(uint64 => RewardEpoch) public epochs;
    mapping(address => AccountCursor) public cursors;
    mapping(uint64 => mapping(address => uint256)) public eligibleCapitalSeconds;
    mapping(uint64 => mapping(address => bool)) public claimed;

    error InvalidEpoch();
    error InvalidClaim();
    event CampaignConfigured(uint64 start, uint64 end, uint16 targetUtilizationBps);
    event LPRewardsPublished(
        uint64 indexed epoch, uint256 capitalSeconds, uint256 liabilitySeconds, uint256 budget, bytes32 journalHash
    );
    event LPRewardClaimed(uint64 indexed epoch, address indexed account, uint256 amount);

    constructor(AccessController access_, FUSEToken token_, LPShareVault vault_)
        Module(access_)
        EIP712("FUSE LPIncentives", "1")
    {
        token = token_;
        vault = vault_;
        escrow = token_.lpEmissionEscrow();
    }

    function configureCampaign(uint64 start_, uint16 utilizationBps) external onlyGovernance {
        if (
            start != 0 || start_ < block.timestamp || start_ == 0 || utilizationBps == 0 || utilizationBps > 10_000
                || escrow.distributor() != address(this) || address(vault.incentives()) != address(this)
        ) revert InvalidConfiguration();
        start = start_;
        end = start_ + CAMPAIGN_DAYS * 1 days;
        lastUpdate = start_;
        targetUtilizationBps = utilizationBps;
        emit CampaignConfigured(start, end, utilizationBps);
    }

    /// @dev Sum of daily caps is exactly BUDGET. Slots decay linearly to expiry; unused rewards stay escrowed.
    function scheduledBudget(uint64 epoch) public pure returns (uint256) {
        if (epoch == 0 || epoch > CAMPAIGN_DAYS) return 0;
        uint256 d = CAMPAIGN_DAYS;
        uint256 n = epoch;
        uint256 cumulative = Math.mulDiv(BUDGET, n * (2 * d - n), d * d);
        uint256 previous = Math.mulDiv(BUDGET, (n - 1) * (2 * d - n + 1), d * d);
        return cumulative - previous;
    }

    function checkpointGlobal() public {
        if (start == 0 || block.timestamp <= lastUpdate || lastUpdate >= end) return;
        uint64 stop = uint64(Math.min(block.timestamp, end));
        uint64 time = lastUpdate;
        uint256 assets = vault.totalAssets();
        uint256 supply = vault.totalSupply();
        while (time < stop) {
            uint64 epoch = uint64((time - start) / 1 days + 1);
            uint64 boundary = start + epoch * 1 days;
            uint64 until = uint64(Math.min(stop, boundary));
            uint256 duration = until - time;
            capitalSeconds[epoch] += assets * duration;
            if (supply != 0) cumulativeIndex += Math.mulDiv(assets, SCALE, supply) * duration;
            if (until == boundary) indexAtEnd[epoch] = cumulativeIndex;
            time = until;
        }
        lastUpdate = stop;
    }

    function checkpointAccount(address account) public {
        checkpointGlobal();
        if (start == 0 || block.timestamp < start) return;
        uint64 target = uint64((Math.min(block.timestamp, end) - start) / 1 days + 1);
        AccountCursor storage cursor = cursors[account];
        uint64 epoch = cursor.epoch == 0 ? 1 : cursor.epoch;
        uint256 index = cursor.index;
        uint256 shares = (vault.protocolCapital(account) || account == address(vault)) ? 0 : vault.balanceOf(account);
        while (epoch < target) {
            uint256 endpoint = indexAtEnd[epoch];
            eligibleCapitalSeconds[epoch][account] += Math.mulDiv(shares, endpoint - index, SCALE);
            index = endpoint;
            ++epoch;
        }
        if (epoch <= CAMPAIGN_DAYS) {
            eligibleCapitalSeconds[epoch][account] += Math.mulDiv(shares, cumulativeIndex - index, SCALE);
        }
        cursor.epoch = epoch;
        cursor.index = cumulativeIndex;
    }

    function hashUtilization(UtilizationReport calldata report) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(REPORT_TYPEHASH, report, access.signatureVersion())));
    }

    function publishEpoch(UtilizationReport calldata report, bytes calldata settlementSig, bytes calldata riskSig)
        external
        onlyRole(access.LP_REWARD_PUBLISHER())
        whenTradingActive
    {
        if (
            start == 0 || report.epoch == 0 || report.epoch > CAMPAIGN_DAYS || report.epoch <= latestEpoch
                || report.journalHash == bytes32(0) || report.deadline < block.timestamp
        ) revert InvalidEpoch();
        uint256 completed = uint256(start) + uint256(report.epoch) * 1 days;
        if (block.timestamp < completed || block.timestamp >= completed + 1 days) revert InvalidEpoch();
        bytes32 digest = hashUtilization(report);
        access.verify(access.SETTLEMENT_SIGNER(), digest, settlementSig);
        access.verify(access.RISK_SIGNER(), digest, riskSig);
        checkpointGlobal();
        uint256 capital = capitalSeconds[report.epoch];
        if (report.liabilitySeconds > capital) revert InvalidEpoch();
        uint256 budget;
        if (capital != 0 && report.liabilitySeconds != 0) {
            uint256 effective = Math.min(capital, Math.mulDiv(report.liabilitySeconds, 10_000, targetUtilizationBps));
            budget = Math.mulDiv(scheduledBudget(report.epoch), effective, capital);
        }
        latestEpoch = report.epoch;
        totalPublishedBudget += budget;
        assert(totalPublishedBudget <= BUDGET);
        epochs[report.epoch] = RewardEpoch(capital, report.liabilitySeconds, budget, report.journalHash, true);
        emit LPRewardsPublished(report.epoch, capital, report.liabilitySeconds, budget, report.journalHash);
    }

    function earned(uint64 epoch, address account) external returns (uint256) {
        checkpointAccount(account);
        RewardEpoch storage reward = epochs[epoch];
        return reward.capitalSeconds == 0
            ? 0
            : Math.mulDiv(reward.budget, eligibleCapitalSeconds[epoch][account], reward.capitalSeconds);
    }

    /// @notice Anyone may relay, but tokens always go to the capital owner, after 30-day vesting.
    function claim(uint64 epoch, address account) external nonReentrant returns (uint256 amount) {
        RewardEpoch storage reward = epochs[epoch];
        if (
            !reward.published || claimed[epoch][account]
                || block.timestamp < uint256(start) + uint256(epoch) * 1 days + VESTING
        ) revert InvalidClaim();
        checkpointAccount(account);
        amount = reward.capitalSeconds == 0
            ? 0
            : Math.mulDiv(reward.budget, eligibleCapitalSeconds[epoch][account], reward.capitalSeconds);
        if (amount == 0) revert InvalidClaim();
        claimed[epoch][account] = true;
        totalClaimed += amount;
        if (totalClaimed > totalPublishedBudget || totalClaimed > BUDGET) revert InvalidClaim();
        escrow.release(account, amount);
        emit LPRewardClaimed(epoch, account, amount);
    }
}
