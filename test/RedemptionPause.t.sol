// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {RedemptionReserve} from "../src/RedemptionReserve.sol";
import {Module} from "../src/common/Module.sol";
import {ExactTransfer} from "../src/common/ExactTransfer.sol";

contract RedemptionPauseTest is FUSEFixture {
    function setUp() public {
        _deploy();
    }

    function _open(uint16 penalty) private {
        _enableTransfers();
        if (!reserve.redemptionsActive()) reserve.activateRedemptions();
        reserve.openRedemptionEpoch(uint64(block.timestamp),uint64(block.timestamp+1 days),penalty);
    }

    function _redeem(address account,uint256 amount) private {
        vm.startPrank(account);
        token.approve(address(reserve),amount);
        reserve.requestRedeem(amount);
        vm.stopPrank();
    }
    function testBettingPausePreservesRequestsClaimsAndSegregatedBacking() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice,100_000_000 ether);
        _open(0);
        uint256 lpBefore = usdc.balanceOf(address(lp));
        access.pauseTrading();
        assertTrue(reserve.supportsPausedRedemptions());
        _redeem(alice,100_000_000 ether);
        assertEq(token.totalSupply(),900_000_000 ether);
        assertEq(reserve.outstandingUSDC(),35e6);
        vm.expectRevert(Module.TradingPaused.selector);
        custody.deposit(1e6,alice);
        vm.warp(block.timestamp+1 days);
        vm.prank(alice);
        assertEq(reserve.claimRedeemedUSDC(1),35e6);
        assertEq(reserve.outstandingUSDC(),0);
        assertEq(usdc.balanceOf(address(lp)),lpBefore,"backing cannot subsidize LP capital");
        assertTrue(access.tradingPaused());
        vm.prank(alice);
        vm.expectRevert(RedemptionReserve.InvalidRequest.selector);
        reserve.claimRedeemedUSDC(1);
    }

    function testPausedSchedulingAndDelayedStartUseActualSnapshotAndKeepRoleGuards() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice,100_000_000 ether);
        _enableTransfers();
        reserve.activateRedemptions();
        access.pauseTrading();
        uint64 start = uint64(block.timestamp+1 hours);
        uint64 end = start+1 days;
        vm.prank(bob);
        vm.expectRevert(Module.Unauthorized.selector);
        reserve.openRedemptionEpoch(start,end,0);
        reserve.openRedemptionEpoch(start,end,0);
        vm.expectRevert(RedemptionReserve.InvalidEpoch.selector);
        reserve.startEpoch();
        usdc.transfer(address(reserve),1e6);
        vm.warp(start+10 minutes);
        vm.prank(bob);
        reserve.startEpoch();
        (,uint64 actualStart,uint64 actualEnd,,uint256 supply,uint256 available,,) = reserve.epochs(1);
        assertEq(actualStart,start+10 minutes);
        assertEq(actualEnd,end);
        assertEq(supply,1_000_000_000 ether,"locked allocations stay in denominator");
        assertEq(available,351e6);
        usdc.transfer(address(reserve),2e6);
        _redeem(alice,100_000_000 ether);
        assertEq(reserve.outstandingUSDC(),35_100_000,"later funds do not reprice accepted window");
        assertTrue(access.tradingPaused());
    }

    function testPausedRequestCanStartItsScheduledWindowWithoutOperatorResume() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice,100_000_000 ether);
        _enableTransfers();
        reserve.activateRedemptions();
        uint64 start = uint64(block.timestamp+1 hours);
        reserve.openRedemptionEpoch(start,start+1 days,0);
        access.pauseTrading();
        vm.warp(start);
        _redeem(alice,100_000_000 ether);
        assertTrue(reserve.epochStarted(1));
        assertEq(reserve.outstandingUSDC(),35e6);
        vm.expectRevert(RedemptionReserve.InvalidEpoch.selector);
        reserve.startEpoch();
    }

    function testUnclaimedLiabilitiesRemainReservedAcrossPausedWindowsAndClaims() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice,100_000_000 ether);
        vm.warp(block.timestamp+1 days);
        _reward(bob,100_000_000 ether);
        _open(0);
        access.pauseTrading();
        _redeem(alice,100_000_000 ether);
        vm.warp(block.timestamp+1 days);
        reserve.openRedemptionEpoch(uint64(block.timestamp),uint64(block.timestamp+1 days),0);
        (,,,,uint256 supply,uint256 free,,) = reserve.epochs(2);
        assertEq(supply,900_000_000 ether);
        assertEq(free,315e6,"unpaid prior claim excluded from new backing");
        _redeem(bob,100_000_000 ether);
        assertEq(reserve.outstandingUSDC(),70e6);
        vm.prank(alice);
        reserve.claimRedeemedUSDC(1);
        assertEq(reserve.outstandingUSDC(),35e6);
        assertEq(usdc.balanceOf(address(reserve)),315e6);
        vm.warp(block.timestamp+1 days);
        vm.prank(bob);
        reserve.claimRedeemedUSDC(2);
        assertEq(reserve.outstandingUSDC(),0);
        assertEq(usdc.balanceOf(address(reserve)),280e6);
    }

    function testClaimTransferFailureKeepsPausedDebtAndAllowsOneSuccessfulRetry() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice,100_000_000 ether);
        _open(0);
        access.pauseTrading();
        _redeem(alice,100_000_000 ether);
        vm.warp(block.timestamp+1 days);
        usdc.setTaxed(true);
        vm.prank(alice);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        reserve.claimRedeemedUSDC(1);
        assertEq(reserve.outstandingUSDC(),35e6);
        (,,uint256 paid) = reserve.requests(1,alice);
        assertEq(paid,0);
        assertEq(usdc.balanceOf(address(reserve)),350e6);
        usdc.setTaxed(false);
        vm.prank(alice);
        assertEq(reserve.claimRedeemedUSDC(1),35e6);
        assertEq(reserve.outstandingUSDC(),0);
    }

    function testPausedRequestsStillRequireActivationAllowanceAndAnOpenWindow() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice,1 ether);
        access.pauseTrading();
        vm.prank(alice);
        vm.expectRevert(RedemptionReserve.InvalidRequest.selector);
        reserve.requestRedeem(1 ether);
        vm.expectRevert(RedemptionReserve.InvalidEpoch.selector);
        reserve.openRedemptionEpoch(uint64(block.timestamp),uint64(block.timestamp+1 days),0);
        reserve.activateRedemptions();
        vm.expectRevert(RedemptionReserve.InvalidEpoch.selector);
        reserve.openRedemptionEpoch(uint64(block.timestamp),uint64(block.timestamp+1 days),0);
        _enableTransfers();
        reserve.openRedemptionEpoch(uint64(block.timestamp),uint64(block.timestamp+1 days),0);
        vm.prank(alice);
        vm.expectRevert();
        reserve.requestRedeem(1 ether);
    }

    function testFuzzPauseBetweenSplitRequestsCannotChangeEntitlement(uint96 rawAmount,uint96 rawSplit,uint16 rawPenalty) public {
        _seedReserve(10_000_003e6);
        _startRewards();
        uint256 amount = bound(rawAmount,2,100_000_000 ether);
        uint256 split = bound(rawSplit,1,amount-1);
        uint16 penalty = uint16(bound(rawPenalty,0,10_000));
        _reward(alice,amount);
        vm.warp(block.timestamp+1 days);
        _reward(bob,amount);
        _open(penalty);
        _redeem(alice,split);
        access.pauseTrading();
        _redeem(bob,amount);
        _redeem(alice,amount-split);
        (,uint256 aliceAccrued,) = reserve.requests(1,alice);
        (,uint256 bobAccrued,) = reserve.requests(1,bob);
        assertEq(aliceAccrued,bobAccrued);
        assertEq(token.totalSupply(),1_000_000_000 ether-2*amount);
        assertEq(reserve.outstandingUSDC(),aliceAccrued+bobAccrued);
        assertLe(reserve.outstandingUSDC(),usdc.balanceOf(address(reserve)));
    }
}
