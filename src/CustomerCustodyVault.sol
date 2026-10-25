// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {ExactTransfer} from "./common/ExactTransfer.sol";

contract CustomerCustodyVault is Module, ReentrancyGuard {
    using ExactTransfer for IERC20;
    enum DepositStatus {
        None,
        Pending,
        Credited,
        Refunded
    }

    struct Deposit {
        address depositor;
        address beneficiary;
        uint256 amount;
        uint64 timestamp;
        uint64 creditedEpoch;
        DepositStatus status;
    }

    IERC20 public immutable usdc;
    uint256 public immutable refundTimeout;
    address public settlementController;
    address public withdrawalGateway;
    address public lpVault;
    uint256 public nextDepositId = 1;
    uint256 public uncreditedBalance;
    uint256 public customerLiabilityUSDC;
    mapping(uint256 => Deposit) public deposits;
    mapping(bytes32 => bool) public paidAuthorizations;

    error InvalidDeposit();
    error InsufficientBacking();
    event Deposited(uint256 indexed id, address indexed depositor, address indexed beneficiary, uint256 amount);
    event DepositCredited(uint256 indexed id, uint64 indexed epoch);
    event DepositRefunded(uint256 indexed id, address indexed depositor, uint256 amount);
    event UserPaid(address indexed recipient, uint256 amount, bytes32 indexed authorizationId);
    event RealizedLossTransferred(uint64 indexed epoch, uint256 amount);

    constructor(AccessController access_, IERC20 usdc_, uint256 refundTimeout_) Module(access_) {
        if (address(usdc_) == address(0) || refundTimeout_ == 0) revert InvalidConfiguration();
        usdc = usdc_;
        refundTimeout = refundTimeout_;
    }

    function configure(address controller, address gateway, address lp) external onlyGovernance {
        if (
            settlementController != address(0) || controller.code.length == 0 || gateway.code.length == 0
                || lp.code.length == 0
        ) {
            revert InvalidConfiguration();
        }
        settlementController = controller;
        withdrawalGateway = gateway;
        lpVault = lp;
    }

    modifier onlySettlement() {
        if (msg.sender != settlementController) revert Unauthorized();
        _;
    }

    function deposit(uint256 amount, address beneficiary) external nonReentrant whenTradingActive returns (uint256 id) {
        if (amount == 0 || beneficiary == address(0) || settlementController == address(0)) revert InvalidDeposit();
        id = nextDepositId++;
        deposits[id] = Deposit(msg.sender, beneficiary, amount, uint64(block.timestamp), 0, DepositStatus.Pending);
        uncreditedBalance += amount;
        usdc.pull(msg.sender, amount);
        emit Deposited(id, msg.sender, beneficiary, amount);
    }

    function acknowledgeDeposits(uint256[] calldata ids, uint64 epoch) external onlySettlement {
        for (uint256 i; i < ids.length; ++i) {
            Deposit storage receipt = deposits[ids[i]];
            if (receipt.status != DepositStatus.Pending) revert InvalidDeposit();
            receipt.status = DepositStatus.Credited;
            receipt.creditedEpoch = epoch;
            uncreditedBalance -= receipt.amount;
            emit DepositCredited(ids[i], epoch);
        }
    }

    /// @notice Anyone may trigger a refund, but it always returns to the original payer.
    function refundUncreditedDeposit(uint256 id) external nonReentrant {
        Deposit storage receipt = deposits[id];
        if (receipt.status != DepositStatus.Pending || block.timestamp < uint256(receipt.timestamp) + refundTimeout) {
            revert InvalidDeposit();
        }
        receipt.status = DepositStatus.Refunded;
        uncreditedBalance -= receipt.amount;
        usdc.push(receipt.depositor, receipt.amount);
        emit DepositRefunded(id, receipt.depositor, receipt.amount);
    }

    function payUser(address recipient, uint256 amount, bytes32 authorizationId) external nonReentrant {
        if (msg.sender != withdrawalGateway) revert Unauthorized();
        if (paidAuthorizations[authorizationId] || amount == 0 || amount > customerLiabilityUSDC) {
            revert InsufficientBacking();
        }
        paidAuthorizations[authorizationId] = true;
        customerLiabilityUSDC -= amount;
        _requireBacking(amount);
        usdc.push(recipient, amount);
        emit UserPaid(recipient, amount, authorizationId);
    }

    function transferRealizedLossToLP(uint256 amount, uint64 epoch) external onlySettlement nonReentrant {
        _requireBacking(amount);
        usdc.push(lpVault, amount);
        emit RealizedLossTransferred(epoch, amount);
    }

    function finalizeLiability(uint256 liability) external onlySettlement {
        _requireBacking(liability);
        customerLiabilityUSDC = liability;
    }

    function _requireBacking(uint256 amount) private view {
        if (usdc.balanceOf(address(this)) < uncreditedBalance + amount) revert InsufficientBacking();
    }
}
