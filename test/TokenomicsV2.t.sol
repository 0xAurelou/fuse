// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {RewardDistributor} from "../src/RewardDistributor.sol";
import {LPVault} from "../src/LPVault.sol";
import {RedemptionReserve} from "../src/RedemptionReserve.sol";

contract TokenomicsV2Test is FUSEFixture {
    function setUp() public {
        _deploy();
    }

    function testFiniteEmissionHorizonExpiresUnusedBudgets() public {
        _startRewards();
        vm.warp(rewards.emissionEnd());
        assertEq(rewards.nextEpochCap(), 0);
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(1, keccak256("root"), 1, keccak256("manifest"));
        assertEq(rewards.totalAllocated(), 0);
        assertEq(token.balanceOf(address(token.emissionEscrow())), 600_000_000 ether);
    }

    function testExpiredEmissionSlotsCannotBeCaughtUp() public {
        _startRewards();
        vm.warp(block.timestamp + 3 days);
        assertEq(rewards.nextEpochCap(), 437_400_000 ether);
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(1, keccak256("root"), 500_000_000 ether, keccak256("manifest"));
        rewards.publishEpoch(1, keccak256("root"), 1 ether, keccak256("manifest"));
        assertEq(rewards.lastEmissionSlot(), 4);
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(2, keccak256("root2"), 1 ether, keccak256("manifest2"));
        vm.warp(block.timestamp + 1 days);
        rewards.publishEpoch(2, keccak256("root2"), 1 ether, keccak256("manifest2"));
    }

    function testReserveRampTwoTimesCapitalAndZeroAllocation() public {
        uint256 id = custody.deposit(1000e6, alice);
        _settle(-1000e6, 0, _ids(id));
        uint256 equity = lp.accountedBalance();
        (uint256 amount, uint256 bps) = lp.reserveAllowance(equity / 2);
        assertEq(amount, 0);
        assertEq(bps, 1166);
        (amount, bps) = lp.reserveAllowance(equity / 3);
        assertEq(bps, 3500);
        assertEq(amount, 350e6);
        lp.setReserveAllocationBps(0);
        (amount,) = lp.reserveAllowance(0);
        assertEq(amount, 0);
    }

    function testUnconsumedOldProfitCannotDistributeBelowHistoricalPeak() public {
        uint256 id = custody.deposit(1000e6, alice);
        _settle(-1000e6, 0, _ids(id));
        _fundReserve(1e6);
        _settle(100e6, 100e6, new uint256[](0));
        (uint256 amount,) = lp.reserveAllowance(0);
        assertEq(amount, 0);
        _settle(-100e6, 0, new uint256[](0));
        (amount,) = lp.reserveAllowance(0);
        assertGt(amount, 0);
    }

    function testTransfersMustBeEnabledBeforeRedemptionOpens() public {
        _seedReserve(1000e6);
        reserve.activateRedemptions();
        vm.expectRevert(RedemptionReserve.InvalidEpoch.selector);
        reserve.openRedemptionEpoch(uint64(block.timestamp), uint64(block.timestamp + 1 days), 1000);
    }

    function testFutureEpochTakesSnapshotOnActualStart() public {
        _seedReserve(1000e6);
        _enableTransfers();
        reserve.activateRedemptions();
        uint64 start = uint64(block.timestamp + 1 hours);
        reserve.openRedemptionEpoch(start, start + 1 days, 1000);
        (,,,, uint256 supply, uint256 backing,,) = reserve.epochs(1);
        assertEq(supply, 0);
        assertEq(backing, 0);
        usdc.transfer(address(reserve), 1e6);
        vm.warp(start);
        reserve.startEpoch();
        (,,,, supply, backing,,) = reserve.epochs(1);
        assertEq(supply, token.totalSupply());
        assertEq(backing, 351e6);
        usdc.transfer(address(reserve), 2e6);
        (,,,,, backing,,) = reserve.epochs(1);
        assertEq(backing, 351e6);
    }

    function testFinalOutstandingSupplyCannotBurnWithoutResidualPolicy() public {
        // Release each immutable escrow under explicit test manifests.
        _startRewards();
        _reward(alice, 600_000_000 ether);
        _enableTransfers();
        bytes32 leaf = token.treasuryEscrow().allocationLeaf(0, alice, 350_000_000 ether);
        token.treasuryEscrow().approveAllocationPolicy(leaf, keccak256("test policy"));
        token.treasuryEscrow().claim(0, alice, 350_000_000 ether, new bytes32[](0));
        token.lpEmissionEscrow().setDistributor(address(this));
        token.lpEmissionEscrow().release(alice, 50_000_000 ether);
        _seedReserve(1000e6);
        reserve.activateRedemptions();
        reserve.openRedemptionEpoch(uint64(block.timestamp), uint64(block.timestamp + 1 days), 1000);
        vm.startPrank(alice);
        token.approve(address(reserve), type(uint256).max);
        uint256 outstanding = token.totalSupply();
        vm.expectRevert(RedemptionReserve.InvalidRequest.selector);
        reserve.requestRedeem(outstanding);
        reserve.requestRedeem(token.totalSupply() - 1);
        vm.expectRevert(RedemptionReserve.InvalidRequest.selector);
        reserve.requestRedeem(1);
        vm.stopPrank();
        assertEq(token.totalSupply(), 1);
    }
}
