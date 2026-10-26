// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccessController} from "../../src/AccessController.sol";
import {CustomerCustodyVault} from "../../src/CustomerCustodyVault.sol";
import {LPVault} from "../../src/LPVault.sol";
import {SettlementController} from "../../src/SettlementController.sol";
import {WithdrawalGateway} from "../../src/WithdrawalGateway.sol";
import {FUSEToken} from "../../src/FUSEToken.sol";
import {RewardDistributor} from "../../src/RewardDistributor.sol";
import {RedemptionReserve} from "../../src/RedemptionReserve.sol";
import {ISettlementView} from "../../src/interfaces/ISettlementView.sol";

contract MockUSDC is ERC20 {
    bool public taxed;
    address public callbackTarget;
    bytes public callbackData;
    bool public callbackSucceeded;
    constructor() ERC20("Mock USDC", "USDC") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function setTaxed(bool taxed_) external {
        taxed = taxed_;
    }

    function setCallback(address target, bytes calldata data) external {
        callbackTarget = target;
        callbackData = data;
    }

    function _update(address from, address to, uint256 amount) internal override {
        if (taxed && from != address(0) && to != address(0) && amount > 0) {
            super._update(from, address(0), 1);
            --amount;
        }
        super._update(from, to, amount);
        if (from != address(0) && callbackTarget != address(0)) {
            (callbackSucceeded,) = callbackTarget.call(callbackData);
        }
    }
}

abstract contract FUSEFixture is Test {
    AccessController internal access;
    MockUSDC internal usdc;
    CustomerCustodyVault internal custody;
    LPVault internal lp;
    SettlementController internal controller;
    WithdrawalGateway internal gateway;
    FUSEToken internal token;
    RewardDistributor internal rewards;
    RedemptionReserve internal reserve;
    uint256 internal constant SETTLEMENT_KEY = 0x111;
    uint256 internal constant RISK_KEY = 0x222;
    uint256 internal constant WITHDRAWAL_KEY = 0x333;
    uint256 internal constant ALICE_KEY = 0x444;
    address internal alice;
    address internal bob = address(0xB0B);
    uint256 internal reserveNonce;

    function _deploy() internal {
        vm.warp(1_700_000_000);
        alice = vm.addr(ALICE_KEY);
        access = new AccessController(address(this));
        usdc = new MockUSDC();
        custody = new CustomerCustodyVault(access, usdc, 1 days);
        lp = new LPVault(access, usdc);
        controller = new SettlementController(access, custody, lp);
        gateway = new WithdrawalGateway(access, custody, ISettlementView(address(controller)));
        token = new FUSEToken(access, 2 days);
        rewards = new RewardDistributor(access, token);
        reserve = new RedemptionReserve(access, usdc, token, address(lp));
        custody.configure(address(controller), address(gateway), address(lp));
        lp.configure(address(custody), ISettlementView(address(controller)), address(reserve));
        token.setRedemptionReserve(address(reserve));
        token.emissionEscrow().setDistributor(address(rewards));
        access.setSigner(access.SETTLEMENT_SIGNER(), vm.addr(SETTLEMENT_KEY));
        access.setSigner(access.RISK_SIGNER(), vm.addr(RISK_KEY));
        access.setSigner(access.WITHDRAWAL_SIGNER(), vm.addr(WITHDRAWAL_KEY));
        access.grantRole(access.LP_PROVIDER(), address(this));
        access.grantRole(access.EMISSION_PUBLISHER(), address(this));
        access.grantRole(access.REDEMPTION_SCHEDULER(), address(this));
        access.grantRole(access.GUARDIAN(), address(this));
        usdc.mint(address(this), 1e18);
        usdc.approve(address(custody), type(uint256).max);
        usdc.approve(address(lp), type(uint256).max);
        lp.depositLP(1_000_000e6);
    }

    function _sign(uint256 key, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    function _ids(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    function _report(int256 pnl, uint256 liability, uint256[] memory ids)
        internal
        view
        returns (SettlementController.EpochSettlement memory report)
    {
        uint64 epoch = controller.latestEpoch() + 1;
        int256 profit = lp.cumulativeRealizedProfitUSDC() - pnl;
        uint256 hwm = lp.realizedProfitHWMUSDC();
        if (profit > 0 && uint256(profit) > hwm) hwm = uint256(profit);
        report = SettlementController.EpochSettlement({
            epoch: epoch,
            priorRoot: controller.currentRoot(),
            newRoot: keccak256(abi.encode(epoch)),
            journalHash: keccak256("journal"),
            oracleJournalHash: keccak256("HyperCore BTC oracle journal"),
            fromSequence: controller.lastSequence() + 1,
            toSequence: controller.lastSequence() + 1,
            asOfTimestamp: uint64(block.timestamp),
            netTraderPnLUSDC: pnl,
            customerLiabilityUSDC: liability,
            reportedMaxOpenExposureUSDC: 0,
            reportedRequiredLPCapitalUSDC: 0,
            realizedProfitHWMUSDC: hwm,
            depositBatchHash: keccak256(abi.encode(ids)),
            deadline: block.timestamp + 1 hours
        });
    }

    function _submit(SettlementController.EpochSettlement memory report, uint256[] memory ids) internal {
        bytes32 digest = controller.hashSettlement(report);
        controller.settle(report, ids, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _settle(int256 pnl, uint256 liability, uint256[] memory ids) internal {
        _submit(_report(pnl, liability, ids), ids);
    }

    function _credit(uint256 amount) internal {
        uint256 id = custody.deposit(amount, alice);
        _settle(0, custody.customerLiabilityUSDC() + amount, _ids(id));
    }

    function _authorization(address account, address recipient, uint256 cumulative, bytes32 id)
        internal
        view
        returns (WithdrawalGateway.WithdrawalAuthorization memory)
    {
        return WithdrawalGateway.WithdrawalAuthorization({
            account: account,
            recipient: recipient,
            cumulativeAmountUSDC: cumulative,
            stateVersion: controller.latestEpoch(),
            validUntil: uint64(block.timestamp + 1 hours),
            authorizationId: id,
            accountStateHash: keccak256(abi.encode(account, cumulative))
        });
    }

    function _reserveAuthorization(uint256 amount) internal returns (LPVault.ReserveAuthorization memory) {
        return LPVault.ReserveAuthorization({
            epoch: controller.latestEpoch(),
            checkpointRoot: controller.currentRoot(),
            amountUSDC: amount,
            minLPCapitalUSDC: lp.requiredCapitalUSDC(),
            realizedProfitHWMUSDC: lp.realizedProfitHWMUSDC(),
            authorizationId: bytes32(++reserveNonce),
            deadline: block.timestamp + 1 hours
        });
    }

    function _fundReserve(uint256 amount) internal {
        LPVault.ReserveAuthorization memory authorization = _reserveAuthorization(amount);
        bytes32 digest = lp.hashReserveAuthorization(authorization);
        lp.fundFUSEReserve(authorization, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _enableTransfers() internal {
        if (token.transfersEnabled()) return;
        if (token.transfersEnableAfter() == 0) token.scheduleEnableTransfers();
        if (block.timestamp < token.transfersEnableAfter()) vm.warp(token.transfersEnableAfter());
        token.enableTransfers();
    }

    function _startRewards() internal {
        rewards.configureEmissionSchedule(uint64(block.timestamp), 1 days, token.EMISSION_ALLOCATION(), 1000);
        rewards.configureEmissionHorizon(uint64(block.timestamp + 180 days));
        rewards.activateEmissions();
    }

    function _reward(address recipient, uint256 amount) internal {
        uint64 epoch = rewards.latestEpoch() + 1;
        uint256 ready = uint256(rewards.emissionStart()) + uint256(epoch - 1) * rewards.epochDuration();
        if (block.timestamp < ready) vm.warp(ready);
        rewards.publishEpoch(epoch, rewards.rewardLeaf(epoch, 0, recipient, amount), amount, keccak256("manifest"));
        rewards.claim(epoch, 0, recipient, amount, new bytes32[](0));
    }

    function _seedReserve(uint256 profit) internal {
        uint256 id = custody.deposit(profit, alice);
        _settle(-int256(profit), 0, _ids(id));
        _fundReserve(profit * 3500 / 10_000);
    }
}
