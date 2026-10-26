// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {StdInvariant} from "forge-std/StdInvariant.sol";
import {Test} from "forge-std/Test.sol";
import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {CustomerCustodyVault} from "../src/CustomerCustodyVault.sol";

/// @dev Valid operator transitions exercise the contract accounting; operator truth is offchain.
contract AccountingHandler is FUSEFixture {
    mapping(uint256 => bool) private credited;
    mapping(uint256 => bool) private refunded;
    mapping(address => uint256) private paid;
    uint64 private epochsApplied;
    uint256 private claimNonce;
    uint256 private burned;
    uint256 private previousSupply;
    uint256 private initialUSDCSupply;
    uint256 private lastConsumedHWM;

    constructor() {
        _deploy();
        _startRewards();
        _reward(alice, 100_000_000 ether);
        _reward(bob, 100_000_000 ether);
        _enableTransfers();
        reserve.activateRedemptions();
        vm.prank(alice);
        token.approve(address(reserve), type(uint256).max);
        vm.prank(bob);
        token.approve(address(reserve), type(uint256).max);
        previousSupply = token.totalSupply();
        initialUSDCSupply = usdc.totalSupply();
    }

    function deposit(uint96 rawAmount) external {
        custody.deposit(bound(rawAmount, 1, 1000e6), alice);
    }

    function refund(uint256 rawId) external {
        if (custody.nextDepositId() == 1) return;
        uint256 id = bound(rawId, 1, custody.nextDepositId() - 1);
        (,,, uint64 timestamp,, CustomerCustodyVault.DepositStatus status) = custody.deposits(id);
        if (status != CustomerCustodyVault.DepositStatus.Pending) return;
        if (block.timestamp < uint256(timestamp) + 1 days) vm.warp(uint256(timestamp) + 1 days);
        custody.refundUncreditedDeposit(id);
        refunded[id] = true;
    }

    function settle(uint256 rawId, uint96 rawPnl, bool wins) external {
        uint256[] memory ids = new uint256[](0);
        uint256 available = usdc.balanceOf(address(custody)) - custody.uncreditedBalance();
        uint256 id;
        if (custody.nextDepositId() > 1) {
            id = bound(rawId, 1, custody.nextDepositId() - 1);
            (,, uint256 amount,,, CustomerCustodyVault.DepositStatus status) = custody.deposits(id);
            if (status == CustomerCustodyVault.DepositStatus.Pending) {
                ids = _ids(id);
                available += amount;
            }
        }
        uint256 limit = wins ? lp.accountedBalance() : available;
        uint256 amountPnL = bound(rawPnl, 0, limit < 1000e6 ? limit : 1000e6);
        _settle(
            wins ? int256(amountPnL) : -int256(amountPnL), wins ? available + amountPnL : available - amountPnL, ids
        );
        ++epochsApplied;
        if (ids.length != 0) credited[id] = true;
    }

    function withdraw(uint96 rawAmount, bool useBob) external {
        uint256 liability = custody.customerLiabilityUSDC();
        if (liability == 0 || controller.latestEpoch() == 0) return;
        address account = useBob ? bob : alice;
        uint256 amount = bound(rawAmount, 1, liability < 1000e6 ? liability : 1000e6);
        bytes32 id = keccak256(abi.encode("withdraw", ++claimNonce));
        gateway.claim(
            _authorization(account, account, paid[account] + amount, id),
            _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(_authorization(account, account, paid[account] + amount, id))),
            ""
        );
        paid[account] += amount;
    }

    function fundReserve(uint96 rawAmount) external {
        int256 netProfit = lp.cumulativeRealizedProfitUSDC();
        uint256 consumed = lp.consumedProfitHWMUSDC();
        if (netProfit <= 0 || uint256(netProfit) <= consumed || controller.latestEpoch() == 0) return;
        (uint256 limit,) = lp.reserveAllowance(lp.requiredCapitalUSDC());
        if (limit == 0) return;
        _fundReserve(bound(rawAmount, 1, limit));
        assertGe(lp.consumedProfitHWMUSDC(), lastConsumedHWM);
        lastConsumedHWM = lp.consumedProfitHWMUSDC();
    }

    function openRedemption(uint16 rawPenalty) external {
        uint64 epoch = reserve.latestEpoch();
        if (epoch != 0) {
            (,, uint64 end,,,,,) = reserve.epochs(epoch);
            if (block.timestamp < end) return;
        }
        if (usdc.balanceOf(address(reserve)) <= reserve.outstandingUSDC()) return;
        reserve.openRedemptionEpoch(
            uint64(block.timestamp), uint64(block.timestamp + 1 hours), uint16(bound(rawPenalty, 0, 2000))
        );
    }

    function requestRedemption(uint96 rawAmount, bool useBob) external {
        uint64 epoch = reserve.latestEpoch();
        if (epoch == 0) return;
        (,, uint64 end,,,,,) = reserve.epochs(epoch);
        if (block.timestamp >= end) return;
        address account = useBob ? bob : alice;
        uint256 balance = token.balanceOf(account);
        if (balance == 0) return;
        uint256 amount = bound(rawAmount, 1, balance);
        vm.prank(account);
        reserve.requestRedeem(amount);
        burned += amount;
        assertLe(token.totalSupply(), previousSupply);
        previousSupply = token.totalSupply();
    }

    function claimRedemption(uint256 rawEpoch, bool useBob) external {
        if (reserve.latestEpoch() == 0) return;
        uint64 epoch = uint64(bound(rawEpoch, 1, reserve.latestEpoch()));
        (,, uint64 end,,,,,) = reserve.epochs(epoch);
        if (block.timestamp < end) vm.warp(end);
        address account = useBob ? bob : alice;
        (, uint256 accrued, uint256 claimed) = reserve.requests(epoch, account);
        if (accrued == claimed) return;
        vm.prank(account);
        reserve.claimRedeemedUSDC(epoch);
    }

    function checkDepositsAndCustody() external view {
        uint256 pending;
        for (uint256 id = 1; id < custody.nextDepositId(); ++id) {
            (,, uint256 amount,,, CustomerCustodyVault.DepositStatus status) = custody.deposits(id);
            assertFalse(credited[id] && refunded[id]);
            if (status == CustomerCustodyVault.DepositStatus.Pending) pending += amount;
            if (credited[id]) assertEq(uint256(status), uint256(CustomerCustodyVault.DepositStatus.Credited));
            if (refunded[id]) assertEq(uint256(status), uint256(CustomerCustodyVault.DepositStatus.Refunded));
        }
        assertEq(custody.uncreditedBalance(), pending);
        assertGe(usdc.balanceOf(address(custody)), pending + custody.customerLiabilityUSDC());
        assertEq(controller.latestEpoch(), epochsApplied);
        assertEq(gateway.withdrawnCumulative(alice), paid[alice]);
        assertEq(gateway.withdrawnCumulative(bob), paid[bob]);
    }

    function checkSupplyAndBacking() external view {
        assertEq(token.totalSupply() + burned, token.GENESIS_SUPPLY());
        assertEq(token.totalSupply(), previousSupply);
        assertLe(rewards.totalAllocated(), token.EMISSION_ALLOCATION());
        assertLe(rewards.totalClaimed(), rewards.totalAllocated());
        assertEq(token.balanceOf(address(token.emissionEscrow())) + rewards.totalClaimed(), token.EMISSION_ALLOCATION());
        assertGe(usdc.balanceOf(address(reserve)), reserve.outstandingUSDC());
        uint256 liabilities;
        for (uint64 i = 1; i <= reserve.latestEpoch(); ++i) {
            (, uint256 accruedAlice, uint256 claimedAlice) = reserve.requests(i, alice);
            (, uint256 accruedBob, uint256 claimedBob) = reserve.requests(i, bob);
            liabilities += accruedAlice + accruedBob - claimedAlice - claimedBob;
        }
        assertEq(reserve.outstandingUSDC(), liabilities);
        assertEq(lp.reserveDistributedUSDC(), reserve.totalFundedUSDC());
        assertEq(lp.accountedBalance(), usdc.balanceOf(address(lp)));
        uint256 assets = usdc.balanceOf(address(this)) + usdc.balanceOf(alice) + usdc.balanceOf(bob)
            + usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp)) + usdc.balanceOf(address(reserve));
        assertEq(assets, initialUSDCSupply);
    }
}

contract AccountingInvariantTest is StdInvariant, Test {
    AccountingHandler private handler;

    function setUp() public {
        handler = new AccountingHandler();
        bytes4[] memory selectors = new bytes4[](8);
        selectors[0] = handler.deposit.selector;
        selectors[1] = handler.refund.selector;
        selectors[2] = handler.settle.selector;
        selectors[3] = handler.withdraw.selector;
        selectors[4] = handler.fundReserve.selector;
        selectors[5] = handler.openRedemption.selector;
        selectors[6] = handler.requestRedemption.selector;
        selectors[7] = handler.claimRedemption.selector;
        targetSelector(FuzzSelector(address(handler), selectors));
        targetContract(address(handler));
    }

    function invariantDepositsEpochsAndWithdrawals() public view {
        handler.checkDepositsAndCustody();
    }

    function invariantSupplyReserveAndConservation() public view {
        handler.checkSupplyAndBacking();
    }
}
