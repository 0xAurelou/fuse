// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {ExactTransfer} from "./common/ExactTransfer.sol";
import {FUSEToken} from "./FUSEToken.sol";

contract RedemptionReserve is Module, ReentrancyGuard {
    using ExactTransfer for IERC20;

    struct RedemptionEpoch {
        uint64 epochId;
        uint64 start;
        uint64 end;
        uint16 penaltyBps;
        uint256 supplySnapshot;
        uint256 availableReserveUSDC;
        uint256 requestedFUSE;
        uint256 accruedUSDC;
    }

    struct RedemptionRequest {
        uint256 requestedFUSE;
        uint256 accruedUSDC;
        uint256 claimedUSDC;
    }
    IERC20 public immutable usdc;
    FUSEToken public immutable token;
    address public immutable lpVault;
    uint64 public latestEpoch;
    uint256 public outstandingUSDC;
    uint256 public totalFundedUSDC;
    bool public redemptionsActive;
    mapping(uint64 => RedemptionEpoch) public epochs;
    mapping(uint64 => bool) public epochStarted;
    mapping(uint64 => mapping(address => RedemptionRequest)) public requests;

    error InvalidEpoch();
    error InvalidRequest();
    event RedemptionsActivated();
    event RedemptionEpochScheduled(uint64 indexed epoch, uint64 start, uint64 end, uint16 penaltyBps);
    event ReserveFunded(uint256 amount);
    event RedemptionEpochOpened(
        uint64 indexed epoch, uint64 start, uint64 end, uint16 penaltyBps, uint256 supply, uint256 reserve
    );
    event RedemptionRequested(uint64 indexed epoch, address indexed account, uint256 burnedFUSE, uint256 accruedUSDC);
    event RedemptionClaimed(uint64 indexed epoch, address indexed account, uint256 amount);

    constructor(AccessController access_, IERC20 usdc_, FUSEToken token_, address lpVault_) Module(access_) {
        if (address(usdc_) == address(0) || address(token_) == address(0) || lpVault_ == address(0)) {
            revert InvalidConfiguration();
        }
        usdc = usdc_;
        token = token_;
        lpVault = lpVault_;
    }

    /// @notice Governance approves the residual policy: residual/penalty USDC stays locked as backing.
    function activateRedemptions() external onlyGovernance {
        if (redemptionsActive || token.redemptionReserve() != address(this)) revert InvalidConfiguration();
        redemptionsActive = true;
        emit RedemptionsActivated();
    }

    function fundReserve(uint256 amount) external nonReentrant {
        if (msg.sender != lpVault) revert Unauthorized();
        if (amount == 0) revert InvalidRequest();
        totalFundedUSDC += amount;
        usdc.pull(msg.sender, amount);
        emit ReserveFunded(amount);
    }

    function openRedemptionEpoch(uint64 start, uint64 end, uint16 penaltyBps)
        external
        onlyRole(access.REDEMPTION_SCHEDULER())
        whenTradingActive
    {
        uint256 supply = token.totalSupply();
        if (
            !redemptionsActive || !token.transfersEnabled() || start < block.timestamp || end <= start
                || penaltyBps > 10_000 || supply == 0 || (latestEpoch != 0 && block.timestamp < epochs[latestEpoch].end)
        ) revert InvalidEpoch();
        uint64 epoch = ++latestEpoch;
        epochs[epoch] = RedemptionEpoch(epoch, start, end, penaltyBps, 0, 0, 0, 0);
        emit RedemptionEpochScheduled(epoch, start, end, penaltyBps);
        if (start == block.timestamp) _startEpoch();
    }

    function startEpoch() external nonReentrant whenTradingActive {
        _startEpoch();
    }

    function _startEpoch() private {
        RedemptionEpoch storage epoch = epochs[latestEpoch];
        if (
            latestEpoch == 0 || epochStarted[latestEpoch] || block.timestamp < epoch.start
                || block.timestamp >= epoch.end
        ) revert InvalidEpoch();
        uint256 available = usdc.balanceOf(address(this)) - outstandingUSDC;
        uint256 supply = token.totalSupply();
        if (available == 0 || supply == 0 || !token.transfersEnabled()) revert InvalidEpoch();
        epoch.start = uint64(block.timestamp);
        epoch.supplySnapshot = supply;
        epoch.availableReserveUSDC = available;
        epochStarted[latestEpoch] = true;
        emit RedemptionEpochOpened(latestEpoch, epoch.start, epoch.end, epoch.penaltyBps, supply, available);
    }

    function requestRedeem(uint256 amount) external nonReentrant whenTradingActive {
        RedemptionEpoch storage epoch = epochs[latestEpoch];
        if (latestEpoch == 0 || amount == 0 || block.timestamp < epoch.start || block.timestamp >= epoch.end) {
            revert InvalidRequest();
        }
        if (!epochStarted[latestEpoch]) _startEpoch();
        // No policy exists for penalty residue after the final outstanding burn.
        if (amount >= token.totalSupply()) revert InvalidRequest();
        RedemptionRequest storage request = requests[latestEpoch][msg.sender];
        uint256 cumulative = request.requestedFUSE + amount;
        if (epoch.requestedFUSE + amount > epoch.supplySnapshot) revert InvalidRequest();
        // The fixed genesis supply bounds both multiplications. Single floor, no intermediate rounding.
        uint256 total = Math.mulDiv(
            cumulative * (10_000 - epoch.penaltyBps), epoch.availableReserveUSDC, epoch.supplySnapshot * 10_000
        );
        uint256 additional = total - request.accruedUSDC;
        request.requestedFUSE = cumulative;
        request.accruedUSDC = total;
        epoch.requestedFUSE += amount;
        epoch.accruedUSDC += additional;
        outstandingUSDC += additional;
        token.burnForRedemption(msg.sender, amount);
        assert(outstandingUSDC <= usdc.balanceOf(address(this)));
        emit RedemptionRequested(latestEpoch, msg.sender, amount, additional);
    }

    /// @notice Claims and previously requested entitlements remain available during a guardian pause.
    function claimRedeemedUSDC(uint64 epochId) external nonReentrant returns (uint256 amount) {
        RedemptionEpoch storage epoch = epochs[epochId];
        RedemptionRequest storage request = requests[epochId][msg.sender];
        if (epochId == 0 || epochId > latestEpoch || block.timestamp < epoch.end) revert InvalidRequest();
        amount = request.accruedUSDC - request.claimedUSDC;
        if (amount == 0) revert InvalidRequest();
        request.claimedUSDC = request.accruedUSDC;
        outstandingUSDC -= amount;
        usdc.push(msg.sender, amount);
        emit RedemptionClaimed(epochId, msg.sender, amount);
    }
}
