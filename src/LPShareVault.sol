// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC4626} from "@openzeppelin/contracts/token/ERC20/extensions/ERC4626.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {ExactTransfer} from "./common/ExactTransfer.sol";
import {ISettlementView} from "./interfaces/ISettlementView.sol";

interface ILPUnderwriter {
    function totalLPAssets() external view returns (uint256);
    function requiredCapitalUSDC() external view returns (uint256);
    function openExposureUSDC() external view returns (uint256);
    function navTimestamp() external view returns (uint64);
    function navEpoch() external view returns (uint64);
    function liquidityWindowEpoch() external view returns (uint64);
    function liquidityWindowNonce() external view returns (uint256);
    function settlementController() external view returns (ISettlementView);
    function enableShareEconomics() external;
    function contribute(uint256 amount, address provider) external;
    function reserveExit(uint256 amount) external;
    function payExit(address recipient, uint256 amount) external;
}

interface ILPCapitalRewards {
    function vault() external view returns (address);
    function checkpointGlobal() external;
    function checkpointAccount(address account) external;
}

/// @notice Synchronous ERC-4626 entry and ERC-7540 asynchronous redemption of LP equity.
/// Shares remain invested while pending; claimable USDC is segregated from underwriting.
contract LPShareVault is ERC4626, Module, EIP712, ReentrancyGuard {
    using ExactTransfer for IERC20;
    enum Phase {
        Protocol,
        Whitelisted,
        Public
    }

    struct CapacityAuthorization {
        uint64 epoch;
        bytes32 checkpointRoot;
        uint256 eligibleDemandUSDC;
        uint256 nonce;
        uint256 deadline;
    }

    struct ExitRequest {
        address controller;
        uint64 readyAt;
        uint64 requestedEpoch;
        uint256 shares;
        uint256 assets;
        uint256 claimedShares;
        uint256 claimedAssets;
        bool fulfilled;
        address owner;
    }
    bytes32 public constant CAPACITY_TYPEHASH = keccak256(
        "CapacityAuthorization(uint64 epoch,bytes32 checkpointRoot,uint256 eligibleDemandUSDC,uint256 nonce,uint256 deadline,uint256 signatureVersion)"
    );
    uint256 public constant EXIT_DELAY = 48 hours;
    uint256 public constant MAX_NAV_AGE = 1 hours;
    uint256 public constant MIN_REDEEM_ASSETS = 1e6;
    ILPUnderwriter public immutable underwriter;
    Phase public phase;
    uint256 public hardDepositCap = 5_000_000e6;
    uint16 public targetUtilizationBps = 2000;
    uint256 public eligibleDemandUSDC;
    uint256 public capacityNonce;
    uint256 public capacityValidUntil;
    uint256 public nextRequestId = 1;
    uint256 public queueHead = 1;
    ILPCapitalRewards public incentives;
    mapping(address => bool) public protocolCapital;
    mapping(address => mapping(address => bool)) public isOperator;
    mapping(uint256 => ExitRequest) public exitRequests;
    /// @notice Active request by share owner, including fulfilled but unclaimed exits.
    mapping(address => uint256) public activeRequest;
    /// @notice Claim lookup by controller. Delegated controllers must consent to the requester.
    mapping(address => uint256) public controllerRequest;

    error InvalidRequest();
    error NAVUnavailable();
    error AsyncPreview();
    error NonTransferableShares();
    event PhaseChanged(Phase phase);
    event DepositPolicyChanged(uint256 hardCap, uint16 targetUtilizationBps);
    event CapacityPublished(uint64 indexed epoch, uint256 demandUSDC, uint256 nonce, uint256 validUntil);
    event OperatorSet(address indexed controller, address indexed operator, bool approved);
    event RedeemRequest(
        address indexed controller, address indexed owner, uint256 indexed requestId, address sender, uint256 shares
    );
    event RedeemFulfilled(uint256 indexed requestId, uint256 shares, uint256 assets, uint64 epoch);

    constructor(AccessController access_, IERC20 usdc_, ILPUnderwriter underwriter_)
        ERC20("FUSE Underwriting LP", "fLP")
        ERC4626(usdc_)
        Module(access_)
        EIP712("FUSE LPShareVault", "1")
    {
        underwriter = underwriter_;
    }

    modifier onlyUnderwriter() {
        if (msg.sender != address(underwriter)) revert Unauthorized();
        _;
    }

    function share() external view returns (address) {
        return address(this);
    }

    function supportsInterface(bytes4 id) external pure returns (bool) {
        return id == 0x01ffc9a7 || id == 0xe3bc4e65 || id == 0x2f0a18c5 || id == 0x620ee8e4;
    }

    function _decimalsOffset() internal pure override returns (uint8) {
        return 12;
    }

    function totalAssets() public view override returns (uint256) {
        return underwriter.totalLPAssets();
    }

    function transfer(address, uint256) public pure override(ERC20, IERC20) returns (bool) {
        revert NonTransferableShares();
    }

    function transferFrom(address, address, uint256) public pure override(ERC20, IERC20) returns (bool) {
        revert NonTransferableShares();
    }

    function setPhase(Phase next) external onlyGovernance {
        if (uint8(next) != uint8(phase) + 1) revert InvalidConfiguration();
        _requireNAV();
        underwriter.enableShareEconomics();
        phase = next;
        emit PhaseChanged(next);
    }

    function setDepositPolicy(uint256 hardCap, uint16 utilizationBps) external onlyGovernance {
        if (utilizationBps == 0 || utilizationBps > 10_000) revert InvalidConfiguration();
        hardDepositCap = hardCap;
        targetUtilizationBps = utilizationBps;
        emit DepositPolicyChanged(hardCap, utilizationBps);
    }

    function setIncentives(ILPCapitalRewards rewards) external onlyGovernance {
        if (address(incentives) != address(0) || address(rewards).code.length == 0 || rewards.vault() != address(this))
        {
            revert InvalidConfiguration();
        }
        incentives = rewards;
    }

    function checkpointGlobal() public {
        if (address(incentives) != address(0)) incentives.checkpointGlobal();
    }

    function _checkpointAccount(address account) private {
        checkpointGlobal();
        if (address(incentives) != address(0)) incentives.checkpointAccount(account);
    }

    function hashCapacity(CapacityAuthorization calldata a) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(CAPACITY_TYPEHASH, a, access.signatureVersion())));
    }

    function publishCapacity(CapacityAuthorization calldata a, bytes calldata settlementSig, bytes calldata riskSig)
        external
    {
        ISettlementView controller = underwriter.settlementController();
        if (
            a.epoch == 0 || a.epoch != controller.latestEpoch() || a.checkpointRoot != controller.currentRoot()
                || a.nonce != capacityNonce + 1 || a.deadline < block.timestamp
                || a.deadline > block.timestamp + MAX_NAV_AGE
        ) revert InvalidRequest();
        bytes32 digest = hashCapacity(a);
        access.verify(access.SETTLEMENT_SIGNER(), digest, settlementSig);
        access.verify(access.RISK_SIGNER(), digest, riskSig);
        eligibleDemandUSDC = a.eligibleDemandUSDC;
        capacityNonce = a.nonce;
        capacityValidUntil = a.deadline;
        emit CapacityPublished(a.epoch, a.eligibleDemandUSDC, a.nonce, a.deadline);
    }

    function depositCap() public view returns (uint256) {
        if (phase == Phase.Protocol) return hardDepositCap;
        if (block.timestamp > capacityValidUntil) return 0;
        // Saturate before mulDiv so arbitrary signed demand cannot make views revert.
        if (eligibleDemandUSDC >= Math.mulDiv(hardDepositCap, targetUtilizationBps, 10_000, Math.Rounding.Ceil)) {
            return hardDepositCap;
        }
        return Math.min(hardDepositCap, Math.mulDiv(eligibleDemandUSDC, 10_000, targetUtilizationBps));
    }

    function _navAvailable() private view returns (bool) {
        uint64 timestamp = underwriter.navTimestamp();
        return timestamp != 0 && timestamp <= block.timestamp && block.timestamp - timestamp <= MAX_NAV_AGE
            && underwriter.openExposureUSDC() == 0;
    }

    function _requireNAV() private view {
        if (!_navAvailable()) revert NAVUnavailable();
    }

    function _liquidityOpen() private view returns (bool) {
        return access.tradingPaused() && underwriter.liquidityWindowEpoch() == underwriter.navEpoch()
            && underwriter.liquidityWindowNonce() == access.pauseNonce();
    }

    function maxDeposit(address receiver) public view override returns (uint256) {
        if (receiver == address(0)) return 0;
        if (phase != Phase.Public && !access.hasRole(access.LP_PROVIDER(), receiver)) return 0;
        if (underwriter.navEpoch() != 0 && !_navAvailable()) return 0;
        if (phase != Phase.Protocol && (!_navAvailable() || !_liquidityOpen())) return 0;
        if (totalSupply() != 0 && totalAssets() == 0) return 0;
        uint256 cap = depositCap();
        uint256 equity = totalAssets();
        return cap > equity ? cap - equity : 0;
    }

    function maxMint(address receiver) public view override returns (uint256) {
        return convertToShares(maxDeposit(receiver));
    }

    function deposit(uint256 assets, address receiver) public override nonReentrant returns (uint256) {
        return super.deposit(assets, receiver);
    }

    function mint(uint256 shares, address receiver) public override nonReentrant returns (uint256) {
        return super.mint(shares, receiver);
    }

    function _deposit(address caller, address receiver, uint256 assets, uint256 shares) internal override {
        if (assets == 0 || shares == 0) revert InvalidRequest();
        _checkpointAccount(receiver);
        uint256 beforeEquity = totalAssets();
        IERC20 token = IERC20(asset());
        token.pull(caller, assets);
        token.push(address(underwriter), assets);
        if (totalAssets() != beforeEquity || assets > maxDeposit(receiver)) revert NAVUnavailable();
        underwriter.contribute(assets, caller);
        if (phase == Phase.Protocol) protocolCapital[receiver] = true;
        _mint(receiver, shares);
        emit Deposit(caller, receiver, assets, shares);
    }

    /// @dev Legacy direct LP deposits still mint shares. Only the underwriter can call this before recording assets.
    function recordDeposit(address provider, uint256 assets) external onlyUnderwriter returns (uint256 shares) {
        if (assets == 0 || assets > maxDeposit(provider)) revert InvalidRequest();
        _checkpointAccount(provider);
        shares = previewDeposit(assets);
        if (shares == 0) revert InvalidRequest();
        if (phase == Phase.Protocol) protocolCapital[provider] = true;
        _mint(provider, shares);
        emit Deposit(provider, provider, assets, shares);
    }

    function setOperator(address operator, bool approved) external returns (bool) {
        if (operator == msg.sender) revert InvalidRequest();
        isOperator[msg.sender][operator] = approved;
        emit OperatorSet(msg.sender, operator, approved);
        return true;
    }

    function requestRedeem(uint256 shares, address controller, address owner) external nonReentrant returns (uint256) {
        if (msg.sender != owner && !isOperator[owner][msg.sender]) _spendAllowance(owner, msg.sender, shares);
        return _request(shares, controller, owner);
    }

    function requestLPExitFor(address owner) external onlyUnderwriter nonReentrant returns (uint256) {
        return _request(balanceOf(owner), owner, owner);
    }

    /// @notice Minimum request size at the current accounted NAV, rounded up to cover 1 USDC.
    function minRedeemShares() public view returns (uint256) {
        return _convertToShares(MIN_REDEEM_ASSETS, Math.Rounding.Ceil);
    }

    function _request(uint256 shares, address controller, address owner) private returns (uint256 id) {
        if (
            phase == Phase.Protocol || shares < minRedeemShares() || controller == address(0) || owner == address(this)
                || activeRequest[owner] != 0 || controllerRequest[controller] != 0
        ) revert InvalidRequest();
        if (controller != owner) {
            if (!isOperator[owner][controller]) revert Unauthorized();
            // The owner's approval alone is insufficient: anyone can appoint a victim
            // as their operator. The controller must also authorize use of its slot.
            _authorizeController(controller);
        }
        _checkpointAccount(owner);
        _transfer(owner, address(this), shares);
        id = nextRequestId++;
        activeRequest[owner] = id;
        controllerRequest[controller] = id;
        ExitRequest storage r = exitRequests[id];
        r.owner = owner;
        r.controller = controller;
        r.shares = shares;
        r.readyAt = uint64(block.timestamp + EXIT_DELAY);
        r.requestedEpoch = underwriter.navEpoch();
        emit RedeemRequest(controller, owner, id, msg.sender, shares);
    }

    function pendingRedeemRequest(uint256 id, address controller) external view returns (uint256) {
        ExitRequest storage r = exitRequests[id];
        return r.controller == controller && !r.fulfilled ? r.shares : 0;
    }

    function claimableRedeemRequest(uint256 id, address controller) external view returns (uint256) {
        ExitRequest storage r = exitRequests[id];
        return r.controller == controller && r.fulfilled ? r.shares - r.claimedShares : 0;
    }

    function fulfillRedeem(uint256 id) external nonReentrant {
        ExitRequest storage r = exitRequests[id];
        if (
            id != queueHead || id == nextRequestId || r.fulfilled || block.timestamp < r.readyAt
                || underwriter.navEpoch() <= r.requestedEpoch || underwriter.navTimestamp() < r.readyAt
        ) revert InvalidRequest();
        _requireNAV();
        if (!_liquidityOpen()) revert NAVUnavailable();
        checkpointGlobal();
        uint256 assets = convertToAssets(r.shares);
        uint256 equity = totalAssets();
        uint256 required = underwriter.requiredCapitalUSDC();
        if (assets > equity || required > (equity - assets) / 2) revert InvalidRequest();
        r.assets = assets;
        r.fulfilled = true;
        ++queueHead;
        _burn(address(this), r.shares);
        underwriter.reserveExit(assets);
        emit RedeemFulfilled(id, r.shares, assets, underwriter.navEpoch());
    }

    function previewRedeem(uint256) public pure override returns (uint256) {
        revert AsyncPreview();
    }

    function previewWithdraw(uint256) public pure override returns (uint256) {
        revert AsyncPreview();
    }

    function maxRedeem(address controller) public view override returns (uint256) {
        ExitRequest storage r = exitRequests[controllerRequest[controller]];
        return r.fulfilled ? r.shares - r.claimedShares : 0;
    }

    function maxWithdraw(address controller) public view override returns (uint256) {
        ExitRequest storage r = exitRequests[controllerRequest[controller]];
        return r.fulfilled ? r.assets - r.claimedAssets : 0;
    }

    function redeem(uint256 shares, address receiver, address controller)
        public
        override
        nonReentrant
        returns (uint256 assets)
    {
        _authorizeController(controller);
        ExitRequest storage r = exitRequests[controllerRequest[controller]];
        if (shares == 0 || shares > maxRedeem(controller)) revert InvalidRequest();
        assets = Math.mulDiv(r.claimedShares + shares, r.assets, r.shares) - r.claimedAssets;
        _claim(r, receiver, shares, assets);
    }

    function withdraw(uint256 assets, address receiver, address controller)
        public
        override
        nonReentrant
        returns (uint256 shares)
    {
        _authorizeController(controller);
        ExitRequest storage r = exitRequests[controllerRequest[controller]];
        if (assets == 0 || assets > maxWithdraw(controller)) revert InvalidRequest();
        shares = assets == maxWithdraw(controller)
            ? maxRedeem(controller)
            : Math.mulDiv(r.claimedAssets + assets, r.shares, r.assets, Math.Rounding.Ceil) - r.claimedShares;
        _claim(r, receiver, shares, assets);
    }

    function claimExitFor(address owner) external onlyUnderwriter nonReentrant returns (uint256 assets) {
        ExitRequest storage r = exitRequests[activeRequest[owner]];
        if (r.controller != owner) revert InvalidRequest();
        uint256 shares = maxRedeem(owner);
        if (shares == 0) revert InvalidRequest();
        assets = maxWithdraw(owner);
        _claim(r, owner, shares, assets);
    }

    function _authorizeController(address controller) private view {
        if (msg.sender != controller && !isOperator[controller][msg.sender]) revert Unauthorized();
    }

    function _claim(ExitRequest storage r, address receiver, uint256 shares, uint256 assets) private {
        r.claimedShares += shares;
        r.claimedAssets += assets;
        if (r.claimedShares == r.shares) {
            activeRequest[r.owner] = 0;
            controllerRequest[r.controller] = 0;
        }
        underwriter.payExit(receiver, assets);
        emit Withdraw(msg.sender, receiver, r.controller, assets, shares);
    }
}
