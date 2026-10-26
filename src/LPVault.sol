// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {ExactTransfer} from "./common/ExactTransfer.sol";
import {ISettlementView} from "./interfaces/ISettlementView.sol";
import {LPShareVault, ILPUnderwriter} from "./LPShareVault.sol";

interface IReserveFunding {
    function fundReserve(uint256 amount) external;
}

contract LPVault is Module, EIP712, ReentrancyGuard {
    using ExactTransfer for IERC20;
    using SafeERC20 for IERC20;

    struct ReserveAuthorization {
        uint64 epoch;
        bytes32 checkpointRoot;
        uint256 amountUSDC;
        uint256 minLPCapitalUSDC;
        uint256 realizedProfitHWMUSDC;
        bytes32 authorizationId;
        uint256 deadline;
    }
    bytes32 public constant RESERVE_TYPEHASH = keccak256(
        "ReserveAuthorization(uint64 epoch,bytes32 checkpointRoot,uint256 amountUSDC,uint256 minLPCapitalUSDC,uint256 realizedProfitHWMUSDC,bytes32 authorizationId,uint256 deadline,uint256 signatureVersion)"
    );

    IERC20 public immutable usdc;
    LPShareVault public immutable shareVault;
    address public custody;
    ISettlementView public settlementController;
    address public reserve;
    int256 public cumulativeRealizedProfitUSDC;
    uint256 public realizedProfitHWMUSDC;
    uint256 public consumedProfitHWMUSDC;
    uint256 public reserveDistributedUSDC;
    uint256 public requiredCapitalUSDC;
    uint256 public accountedBalance;
    uint16 public reserveAllocationBps = 3500;
    bool public shareEconomics;
    uint256 public reserveFeeAccruedUSDC;
    uint256 public reservedExitUSDC;
    uint256 public highWaterAssets = 1;
    uint256 public highWaterShares = 1e12;
    uint64 public navEpoch;
    uint64 public navTimestamp;
    uint256 public openExposureUSDC;
    uint256 public liquidityWindowNonce;
    uint64 public liquidityWindowEpoch;
    uint256 public peakNAVRay = 1e15;
    uint16 public maxDrawdownBps;
    mapping(bytes32 => bool) public usedReserveAuthorizations;

    error InvalidSettlement();
    error InvalidReserveAuthorization();
    error InsufficientCapital();
    error PublicLPExitsDisabled();
    event LPDeposited(address indexed provider, uint256 amount);
    event NetTraderWinsFunded(uint64 indexed epoch, uint256 amount);
    event NetTraderLossesReceived(uint64 indexed epoch, uint256 amount);
    event ReserveFunded(bytes32 indexed authorizationId, uint256 amount, uint256 consumedProfitHWM);
    event ReserveAllocationChanged(uint16 bps);
    event ReserveFeeAccrued(uint256 amount, uint256 totalAccrued, uint256 highWaterAssets, uint256 highWaterShares);
    event LPExitPaid(address indexed recipient, uint256 amount);
    event LPExitReserved(uint256 amount);

    constructor(AccessController access_, IERC20 usdc_) Module(access_) EIP712("FUSE LPVault", "1") {
        if (address(usdc_) == address(0)) revert InvalidConfiguration();
        usdc = usdc_;
        shareVault = new LPShareVault(access_, usdc_, ILPUnderwriter(address(this)));
    }

    function configure(address custody_, ISettlementView controller, address reserve_) external onlyGovernance {
        if (
            custody != address(0) || custody_.code.length == 0 || address(controller).code.length == 0
                || reserve_.code.length == 0
        ) {
            revert InvalidConfiguration();
        }
        custody = custody_;
        settlementController = controller;
        reserve = reserve_;
    }

    modifier onlySettlement() {
        if (msg.sender != address(settlementController)) revert Unauthorized();
        _;
    }

    function depositLP(uint256 amount) external onlyRole(access.LP_PROVIDER()) nonReentrant {
        if (amount == 0) revert InvalidSettlement();
        usdc.pull(msg.sender, amount);
        // Price/mint only after the token call: callbacks must not observe newly
        // issued shares before their contribution has arrived. Accounted equity
        // still excludes these assets until the contribution is recorded below.
        shareVault.recordDeposit(msg.sender, amount);
        accountedBalance += amount;
        emit LPDeposited(msg.sender, amount);
    }

    modifier onlyShares() {
        if (msg.sender != address(shareVault)) revert Unauthorized();
        _;
    }

    function totalLPAssets() public view returns (uint256) {
        uint256 balance = Math.min(accountedBalance, usdc.balanceOf(address(this)));
        uint256 liabilities = reservedExitUSDC + reserveFeeAccruedUSDC;
        return balance > liabilities ? balance - liabilities : 0;
    }

    function enableShareEconomics() external onlyShares {
        shareEconomics = true;
    }

    function contribute(uint256 amount, address provider) external onlyShares nonReentrant {
        if (usdc.balanceOf(address(this)) < accountedBalance + amount) revert InvalidSettlement();
        accountedBalance += amount;
        emit LPDeposited(provider, amount);
    }

    function reserveExit(uint256 amount) external onlyShares {
        if (amount > totalLPAssets() || requiredCapitalUSDC > (totalLPAssets() - amount) / 2) {
            revert InsufficientCapital();
        }
        reservedExitUSDC += amount;
        emit LPExitReserved(amount);
    }

    function payExit(address recipient, uint256 amount) external onlyShares nonReentrant {
        if (amount > reservedExitUSDC) revert InsufficientCapital();
        reservedExitUSDC -= amount;
        accountedBalance -= amount;
        usdc.push(recipient, amount);
        emit LPExitPaid(recipient, amount);
    }

    function fundNetTraderWins(uint64 epoch, uint256 amount) external onlySettlement nonReentrant {
        if (amount > uint256(type(int256).max) || amount > totalLPAssets()) revert InvalidSettlement();
        shareVault.checkpointGlobal();
        accountedBalance -= amount;
        cumulativeRealizedProfitUSDC -= int256(amount);
        usdc.push(custody, amount);
        emit NetTraderWinsFunded(epoch, amount);
    }

    function receiveNetTraderLosses(uint64 epoch, uint256 amount) external onlySettlement {
        if (amount > uint256(type(int256).max) || usdc.balanceOf(address(this)) < accountedBalance + amount) {
            revert InvalidSettlement();
        }
        shareVault.checkpointGlobal();
        accountedBalance += amount;
        cumulativeRealizedProfitUSDC += int256(amount);
        if (cumulativeRealizedProfitUSDC > 0 && uint256(cumulativeRealizedProfitUSDC) > realizedProfitHWMUSDC) {
            realizedProfitHWMUSDC = uint256(cumulativeRealizedProfitUSDC);
        }
        emit NetTraderLossesReceived(epoch, amount);
    }

    function finalizeCapital(uint256 requiredCapital, uint256 reportedHWM) external onlySettlement {
        if (reportedHWM != realizedProfitHWMUSDC) revert InvalidSettlement();
        if (totalLPAssets() < requiredCapital) revert InsufficientCapital();
        requiredCapitalUSDC = requiredCapital;
        _crystallize();
        if (!shareEconomics) return;
        uint256 nav = Math.mulDiv(totalLPAssets() + 1, 1e27, shareVault.totalSupply() + 1e12);
        if (nav > peakNAVRay) peakNAVRay = nav;
        uint256 drawdown = Math.mulDiv(peakNAVRay - nav, 10_000, peakNAVRay);
        if (drawdown > maxDrawdownBps) maxDrawdownBps = uint16(drawdown);
    }

    function finalizeLiquidityCheckpoint(uint64 epoch, uint64 timestamp, uint256 exposure) external onlySettlement {
        navEpoch = epoch;
        navTimestamp = timestamp;
        openExposureUSDC = exposure;
    }

    function openLiquidityWindow() external onlySettlement {
        if (!access.tradingPaused() || openExposureUSDC != 0) revert InvalidSettlement();
        liquidityWindowNonce = access.pauseNonce();
        liquidityWindowEpoch = navEpoch;
    }

    function _crystallize() private {
        if (openExposureUSDC != 0) return;
        shareVault.checkpointGlobal();
        uint256 equity = totalLPAssets();
        uint256 supply = shareVault.totalSupply() + 1e12;
        uint256 threshold = Math.mulDiv(highWaterAssets, supply, highWaterShares, Math.Rounding.Ceil);
        uint256 gross = equity + 1;
        if (gross <= threshold) return;
        if (shareEconomics) {
            uint256 capital = requiredCapitalUSDC;
            uint256 bps = _effectiveBps(equity, capital);
            uint256 fee = Math.mulDiv(gross - threshold, bps, 10_000);
            uint256 free = capital > equity / 2 ? 0 : equity - capital - capital;
            fee = Math.min(fee, free);
            reserveFeeAccruedUSDC += fee;
            gross -= fee;
            emit ReserveFeeAccrued(fee, reserveFeeAccruedUSDC, gross, supply);
        }
        // Update even when capitalization suppressed the fee. Protected retained profits
        // belong to LPs and cannot be charged retroactively after new deposits arrive.
        highWaterAssets = gross;
        highWaterShares = supply;
    }

    function setReserveAllocationBps(uint16 bps) external onlyGovernance {
        if (bps > 3500) revert InvalidConfiguration();
        reserveAllocationBps = bps;
        emit ReserveAllocationChanged(bps);
    }

    /// @notice Candidate v2 policy: recover the historical profit peak, ramp the
    /// allocation with equity/capital, and retain at least twice required capital.
    function reserveAllowance(uint256 minCapital) public view returns (uint256 amount, uint256 effectiveBps) {
        if (shareEconomics) {
            uint256 shareCapital = Math.max(requiredCapitalUSDC, minCapital);
            if (shareCapital > totalLPAssets() / 2) return (0, 0);
            return (reserveFeeAccruedUSDC, 3500);
        }
        uint256 profit = cumulativeRealizedProfitUSDC > 0 ? uint256(cumulativeRealizedProfitUSDC) : 0;
        if (profit < realizedProfitHWMUSDC || profit <= consumedProfitHWMUSDC || reserveAllocationBps == 0) {
            return (0, 0);
        }
        uint256 equity = Math.min(accountedBalance, usdc.balanceOf(address(this)));
        uint256 capital = Math.max(requiredCapitalUSDC, minCapital);
        if (capital > equity / 2) return (0, 0);
        effectiveBps = reserveAllocationBps;
        if (capital != 0 && capital > equity / 3) {
            // floor(cap * (2E-3C)/(3C)); all intermediate scaled products
            // use mulDiv. Subtract before doubling to avoid uint256 overflow.
            uint256 scaled = Math.mulDiv(reserveAllocationBps * 2, equity - capital, capital);
            effectiveBps = (scaled - reserveAllocationBps) / 3;
        }
        amount = Math.min(Math.mulDiv(profit - consumedProfitHWMUSDC, effectiveBps, 10_000), equity - capital - capital);
    }

    function _effectiveBps(uint256 equity, uint256 capital) private view returns (uint256 bps) {
        if (capital > equity / 2) return 0;
        bps = reserveAllocationBps;
        if (capital != 0 && capital > equity / 3) {
            uint256 scaled = Math.mulDiv(bps * 2, equity - capital, capital);
            bps = (scaled - bps) / 3;
        }
    }

    function hashReserveAuthorization(ReserveAuthorization calldata authorization) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(RESERVE_TYPEHASH, authorization, access.signatureVersion())));
    }

    /// @notice Both authorities attest to the latest checkpoint and post-distribution capital.
    function fundFUSEReserve(
        ReserveAuthorization calldata authorization,
        bytes calldata settlementSignature,
        bytes calldata riskSignature
    ) external nonReentrant whenTradingActive {
        if (
            authorization.epoch == 0 || authorization.epoch != settlementController.latestEpoch()
                || authorization.checkpointRoot != settlementController.currentRoot()
                || authorization.deadline < block.timestamp || authorization.amountUSDC == 0
                || authorization.authorizationId == bytes32(0)
                || usedReserveAuthorizations[authorization.authorizationId]
                || authorization.realizedProfitHWMUSDC != realizedProfitHWMUSDC
                || authorization.minLPCapitalUSDC < requiredCapitalUSDC
        ) revert InvalidReserveAuthorization();
        bytes32 digest = hashReserveAuthorization(authorization);
        access.verify(access.SETTLEMENT_SIGNER(), digest, settlementSignature);
        access.verify(access.RISK_SIGNER(), digest, riskSignature);
        (uint256 allowance, uint256 effectiveBps) = reserveAllowance(authorization.minLPCapitalUSDC);
        if (authorization.amountUSDC > allowance || effectiveBps == 0) revert InvalidReserveAuthorization();
        uint256 balance = usdc.balanceOf(address(this));
        if (
            authorization.amountUSDC > accountedBalance || authorization.amountUSDC > balance
                || balance - authorization.amountUSDC < authorization.minLPCapitalUSDC
        ) revert InsufficientCapital();
        usedReserveAuthorizations[authorization.authorizationId] = true;
        shareVault.checkpointGlobal();
        // Round consumed profit up: splitting authorizations cannot increase the allowance.
        consumedProfitHWMUSDC += Math.mulDiv(authorization.amountUSDC, 10_000, effectiveBps, Math.Rounding.Ceil);
        reserveDistributedUSDC += authorization.amountUSDC;
        if (shareEconomics) reserveFeeAccruedUSDC -= authorization.amountUSDC;
        accountedBalance -= authorization.amountUSDC;
        usdc.forceApprove(reserve, authorization.amountUSDC);
        IReserveFunding(reserve).fundReserve(authorization.amountUSDC);
        usdc.forceApprove(reserve, 0);
        if (usdc.balanceOf(address(this)) != balance - authorization.amountUSDC) revert InvalidReserveAuthorization();
        emit ReserveFunded(authorization.authorizationId, authorization.amountUSDC, consumedProfitHWMUSDC);
    }

    function requestLPExit() external returns (uint256) {
        if (!shareEconomics) revert PublicLPExitsDisabled();
        return shareVault.requestLPExitFor(msg.sender);
    }

    function executeLPExit() external returns (uint256) {
        if (!shareEconomics) revert PublicLPExitsDisabled();
        return shareVault.claimExitFor(msg.sender);
    }
}
