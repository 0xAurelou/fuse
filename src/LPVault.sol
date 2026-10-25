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

    constructor(AccessController access_, IERC20 usdc_) Module(access_) EIP712("FUSE LPVault", "1") {
        if (address(usdc_) == address(0)) revert InvalidConfiguration();
        usdc = usdc_;
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
        accountedBalance += amount;
        usdc.pull(msg.sender, amount);
        emit LPDeposited(msg.sender, amount);
    }

    function fundNetTraderWins(uint64 epoch, uint256 amount) external onlySettlement nonReentrant {
        if (amount > uint256(type(int256).max) || amount > accountedBalance) revert InvalidSettlement();
        accountedBalance -= amount;
        cumulativeRealizedProfitUSDC -= int256(amount);
        usdc.push(custody, amount);
        emit NetTraderWinsFunded(epoch, amount);
    }

    function receiveNetTraderLosses(uint64 epoch, uint256 amount) external onlySettlement {
        if (amount > uint256(type(int256).max) || usdc.balanceOf(address(this)) < accountedBalance + amount) {
            revert InvalidSettlement();
        }
        accountedBalance += amount;
        cumulativeRealizedProfitUSDC += int256(amount);
        if (cumulativeRealizedProfitUSDC > 0 && uint256(cumulativeRealizedProfitUSDC) > realizedProfitHWMUSDC) {
            realizedProfitHWMUSDC = uint256(cumulativeRealizedProfitUSDC);
        }
        emit NetTraderLossesReceived(epoch, amount);
    }

    function finalizeCapital(uint256 requiredCapital, uint256 reportedHWM) external onlySettlement {
        if (reportedHWM != realizedProfitHWMUSDC) revert InvalidSettlement();
        if (usdc.balanceOf(address(this)) < requiredCapital) revert InsufficientCapital();
        requiredCapitalUSDC = requiredCapital;
    }

    function setReserveAllocationBps(uint16 bps) external onlyGovernance {
        if (bps == 0 || bps > 5000) revert InvalidConfiguration();
        reserveAllocationBps = bps;
        emit ReserveAllocationChanged(bps);
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
        uint256 profit = cumulativeRealizedProfitUSDC > 0 ? uint256(cumulativeRealizedProfitUSDC) : 0;
        if (
            profit <= consumedProfitHWMUSDC
                || authorization.amountUSDC > Math.mulDiv(profit - consumedProfitHWMUSDC, reserveAllocationBps, 10_000)
        ) revert InvalidReserveAuthorization();
        uint256 balance = usdc.balanceOf(address(this));
        if (
            authorization.amountUSDC > accountedBalance || authorization.amountUSDC > balance
                || balance - authorization.amountUSDC < authorization.minLPCapitalUSDC
        ) revert InsufficientCapital();
        usedReserveAuthorizations[authorization.authorizationId] = true;
        // Round consumed profit up: splitting authorizations cannot increase the allowance.
        consumedProfitHWMUSDC += Math.mulDiv(authorization.amountUSDC, 10_000, reserveAllocationBps, Math.Rounding.Ceil);
        reserveDistributedUSDC += authorization.amountUSDC;
        accountedBalance -= authorization.amountUSDC;
        usdc.forceApprove(reserve, authorization.amountUSDC);
        IReserveFunding(reserve).fundReserve(authorization.amountUSDC);
        usdc.forceApprove(reserve, 0);
        if (usdc.balanceOf(address(this)) != balance - authorization.amountUSDC) revert InvalidReserveAuthorization();
        emit ReserveFunded(authorization.authorizationId, authorization.amountUSDC, consumedProfitHWMUSDC);
    }

    function requestLPExit() external pure {
        revert PublicLPExitsDisabled();
    }

    function executeLPExit() external pure {
        revert PublicLPExitsDisabled();
    }
}
