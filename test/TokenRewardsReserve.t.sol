// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {FUSEToken} from "../src/FUSEToken.sol";
import {RewardDistributor} from "../src/RewardDistributor.sol";
import {RedemptionReserve} from "../src/RedemptionReserve.sol";
import {LPVault} from "../src/LPVault.sol";
import {Module} from "../src/common/Module.sol";
import {TreasuryEscrow} from "../src/AllocationEscrows.sol";

contract TokenRewardsReserveTest is FUSEFixture {
    function setUp() public {
        _deploy();
    }

    function _open(uint16 penalty) internal {
        if (!reserve.redemptionsActive()) reserve.activateRedemptions();
        reserve.openRedemptionEpoch(uint64(block.timestamp), uint64(block.timestamp + 1 days), penalty);
    }

    function _redeem(address user, uint256 amount) internal {
        vm.startPrank(user);
        token.approve(address(reserve), amount);
        reserve.requestRedeem(amount);
        vm.stopPrank();
    }

    function _expectFundingRevert(bytes4 selector, LPVault.ReserveAuthorization memory authorization) internal {
        bytes32 digest = lp.hashReserveAuthorization(authorization);
        bytes memory settlementSig = _sign(SETTLEMENT_KEY, digest);
        bytes memory riskSig = _sign(RISK_KEY, digest);
        vm.expectRevert(selector);
        lp.fundFUSEReserve(authorization, settlementSig, riskSig);
    }

    function testFixedSupplyEscrowsAndTransferTimelock() public {
        assertEq(token.totalSupply(), 1_000_000_000 ether);
        assertEq(token.balanceOf(address(token.emissionEscrow())), 600_000_000 ether);
        assertEq(token.balanceOf(address(token.treasuryEscrow())), 400_000_000 ether);
        _startRewards();
        _reward(alice, 100 ether);
        vm.prank(alice);
        vm.expectRevert(FUSEToken.TransfersDisabled.selector);
        token.transfer(bob, 1 ether);
        token.scheduleEnableTransfers();
        vm.expectRevert(FUSEToken.ActivationNotReady.selector);
        token.enableTransfers();
        vm.warp(block.timestamp + 2 days);
        vm.prank(bob);
        token.enableTransfers();
        vm.prank(alice);
        token.transfer(bob, 1 ether);
        assertEq(token.balanceOf(bob), 1 ether);
        vm.expectRevert(FUSEToken.ActivationNotReady.selector);
        token.scheduleEnableTransfers();
        vm.expectRevert(Module.Unauthorized.selector);
        token.burnForRedemption(alice, 1);
    }

    function testRewardReplayAndImmutableEpoch() public {
        _startRewards();
        _reward(alice, 100 ether);
        assertTrue(rewards.isClaimed(1, 0));
        assertEq(rewards.totalAllocated(), 100 ether);
        vm.expectRevert(RewardDistributor.InvalidClaim.selector);
        rewards.claim(1, 0, alice, 100 ether, new bytes32[](0));
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(1, keccak256("new"), 100 ether, keccak256("manifest"));
    }

    function testTreasuryRequiresApprovedPolicyAndTransferActivation() public {
        TreasuryEscrow treasury = token.treasuryEscrow();
        vm.expectRevert(TreasuryEscrow.InvalidClaim.selector);
        treasury.claim(0, alice, 100 ether, new bytes32[](0));
        bytes32 root = treasury.allocationLeaf(0, alice, 100 ether);
        vm.prank(bob);
        vm.expectRevert(Module.Unauthorized.selector);
        treasury.approveAllocationPolicy(root, keccak256("policy"));
        treasury.approveAllocationPolicy(root, keccak256("policy"));
        vm.expectRevert(TreasuryEscrow.InvalidPolicy.selector);
        treasury.approveAllocationPolicy(root, keccak256("policy"));
        vm.expectRevert(FUSEToken.TransfersDisabled.selector);
        treasury.claim(0, alice, 100 ether, new bytes32[](0));
        assertFalse(treasury.isClaimed(0));
        token.scheduleEnableTransfers();
        vm.warp(block.timestamp + 2 days);
        token.enableTransfers();
        vm.expectRevert(TreasuryEscrow.InvalidClaim.selector);
        treasury.claim(0, bob, 100 ether, new bytes32[](0));
        treasury.claim(0, alice, 100 ether, new bytes32[](0));
        assertEq(token.balanceOf(alice), 100 ether);
        assertEq(treasury.totalReleased(), 100 ether);
        vm.expectRevert(TreasuryEscrow.InvalidClaim.selector);
        treasury.claim(0, alice, 100 ether, new bytes32[](0));
    }

    function testRewardProofCannotChangeRecipientOrAmount() public {
        _startRewards();
        bytes32 root = rewards.rewardLeaf(1, 256, alice, 100 ether);
        rewards.publishEpoch(1, root, 100 ether, keccak256("manifest"));
        vm.expectRevert(RewardDistributor.InvalidClaim.selector);
        rewards.claim(1, 256, bob, 100 ether, new bytes32[](0));
        vm.expectRevert(RewardDistributor.InvalidClaim.selector);
        rewards.claim(1, 256, alice, 99 ether, new bytes32[](0));
        rewards.claim(1, 256, alice, 100 ether, new bytes32[](0));
        assertTrue(rewards.isClaimed(1, 256));
        assertFalse(rewards.isClaimed(1, 0));
    }

    function testRewardBudgetCapsEvenOvercommittedMerkleRoot() public {
        _startRewards();
        bytes32 left = rewards.rewardLeaf(1, 0, alice, 70 ether);
        bytes32 right = rewards.rewardLeaf(1, 1, bob, 70 ether);
        bytes32 root =
            left < right ? keccak256(abi.encodePacked(left, right)) : keccak256(abi.encodePacked(right, left));
        rewards.publishEpoch(1, root, 100 ether, keccak256("manifest"));
        bytes32[] memory proof = new bytes32[](1);
        proof[0] = right;
        rewards.claim(1, 0, alice, 70 ether, proof);
        proof[0] = left;
        vm.expectRevert(RewardDistributor.InvalidClaim.selector);
        rewards.claim(1, 1, bob, 70 ether, proof);
        assertEq(rewards.totalClaimed(), 70 ether);
    }

    function testMiningCapDeclinesAndCannotAllocateBeyondEscrow() public {
        _startRewards();
        _reward(alice, token.EMISSION_ALLOCATION());
        assertEq(rewards.nextEpochCap(), 540_000_000 ether);
        vm.warp(block.timestamp + 1 days);
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(2, keccak256("root"), 1, keccak256("manifest"));
        assertEq(token.balanceOf(address(token.emissionEscrow())), 0);
        assertEq(rewards.totalAllocated(), 600_000_000 ether);
    }

    function testDecliningScheduleAndActivationAreEnforced() public {
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(1, keccak256("root"), 1, keccak256("manifest"));
        _startRewards();
        _reward(alice, 1 ether);
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(2, keccak256("root"), 1, keccak256("manifest"));
        vm.warp(block.timestamp + 1 days);
        vm.expectRevert(RewardDistributor.InvalidEpoch.selector);
        rewards.publishEpoch(2, keccak256("root"), 540_000_001 ether, keccak256("manifest"));
    }

    function testAdjustedProfitHighWaterMarkPreventsReusingProfits() public {
        _seedReserve(1000e6);
        assertEq(reserve.totalFundedUSDC(), 350e6);
        assertEq(lp.consumedProfitHWMUSDC(), 1000e6);
        _expectFundingRevert(LPVault.InvalidReserveAuthorization.selector, _reserveAuthorization(1));
        _settle(400e6, 400e6, new uint256[](0));
        _expectFundingRevert(LPVault.InvalidReserveAuthorization.selector, _reserveAuthorization(1));
        _settle(-400e6, 0, new uint256[](0));
        _expectFundingRevert(LPVault.InvalidReserveAuthorization.selector, _reserveAuthorization(1));
        uint256 id = custody.deposit(100e6, alice);
        _settle(-100e6, 0, _ids(id));
        _fundReserve(35e6);
        assertEq(lp.consumedProfitHWMUSDC(), 1100e6);
        assertEq(reserve.totalFundedUSDC(), 385e6);
    }

    function testReserveFundingReplayAndPostTransferCapital() public {
        uint256 id = custody.deposit(1000e6, alice);
        _settle(-1000e6, 0, _ids(id));
        LPVault.ReserveAuthorization memory authorization = _reserveAuthorization(350e6);
        authorization.minLPCapitalUSDC = usdc.balanceOf(address(lp));
        _expectFundingRevert(LPVault.InsufficientCapital.selector, authorization);
        authorization.minLPCapitalUSDC = 0;
        bytes32 digest = lp.hashReserveAuthorization(authorization);
        lp.fundFUSEReserve(authorization, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
        _expectFundingRevert(LPVault.InvalidReserveAuthorization.selector, authorization);
        assertEq(usdc.balanceOf(address(reserve)), 350e6);
        assertEq(lp.accountedBalance(), usdc.balanceOf(address(lp)));
        vm.expectRevert(Module.Unauthorized.selector);
        reserve.fundReserve(1);
    }

    function testReserveBalanceCannotUnderwriteLPCapital() public {
        _seedReserve(1000e6);
        uint256 balance = usdc.balanceOf(address(lp));
        // A payout that needs reserve backing fails even though combined assets suffice.
        vm.prank(address(controller));
        vm.expectRevert(LPVault.InvalidSettlement.selector);
        lp.fundNetTraderWins(2, balance + 1);
    }

    function testRedemptionSnapshotsEntireSupplyAndRetainsPenalty() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice, 100_000_000 ether);
        _open(1000);
        _redeem(alice, 100_000_000 ether);
        assertEq(token.totalSupply(), 900_000_000 ether);
        assertEq(reserve.outstandingUSDC(), 31_500_000);
        assertEq(usdc.balanceOf(address(reserve)), 350e6);
        vm.warp(block.timestamp + 1 days);
        vm.prank(alice);
        reserve.claimRedeemedUSDC(1);
        assertEq(usdc.balanceOf(alice), 31_500_000);
        assertEq(usdc.balanceOf(address(reserve)), 318_500_000);
        assertEq(reserve.outstandingUSDC(), 0);
        vm.prank(alice);
        vm.expectRevert(RedemptionReserve.InvalidRequest.selector);
        reserve.claimRedeemedUSDC(1);
    }

    function testNextEpochDeductsOutstandingClaimsAndBurnsDoNotChangeActivePrice() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice, 200_000_000 ether);
        _open(2000);
        _redeem(alice, 100_000_000 ether);
        uint256 first = reserve.outstandingUSDC();
        _redeem(alice, 100_000_000 ether);
        assertEq(reserve.outstandingUSDC(), first * 2);
        vm.warp(block.timestamp + 1 days);
        _open(2000);
        (,,,, uint256 supply, uint256 available,,) = reserve.epochs(2);
        assertEq(supply, 800_000_000 ether);
        assertEq(available, 350e6 - reserve.outstandingUSDC());
        access.pauseTrading();
        vm.prank(alice);
        reserve.claimRedeemedUSDC(1);
        assertEq(reserve.outstandingUSDC(), 0);
    }

    function testRedemptionRequiresActivationWindowAndVoluntaryAllowance() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(alice, 100 ether);
        uint64 start = uint64(block.timestamp + 1 hours);
        uint64 end = start + 1 days;
        vm.expectRevert(RedemptionReserve.InvalidEpoch.selector);
        reserve.openRedemptionEpoch(start, end, 1000);
        reserve.activateRedemptions();
        reserve.openRedemptionEpoch(start, end, 1000);
        vm.prank(alice);
        vm.expectRevert(RedemptionReserve.InvalidRequest.selector);
        reserve.requestRedeem(1 ether);
        vm.warp(start);
        vm.prank(alice);
        vm.expectRevert();
        reserve.requestRedeem(1 ether);
        _redeem(alice, 1 ether);
        vm.expectRevert(RedemptionReserve.InvalidEpoch.selector);
        reserve.openRedemptionEpoch(start, end, 1000);
        vm.warp(end);
        vm.prank(alice);
        vm.expectRevert(RedemptionReserve.InvalidRequest.selector);
        reserve.requestRedeem(1 ether);
    }

    function testRedemptionReentrancyCannotDuplicateClaim() public {
        _seedReserve(1000e6);
        _startRewards();
        _reward(address(usdc), 100_000_000 ether);
        _open(1000);
        _redeem(address(usdc), 100_000_000 ether);
        vm.warp(block.timestamp + 1 days);
        usdc.setCallback(address(reserve), abi.encodeCall(reserve.claimRedeemedUSDC, (uint64(1))));
        vm.prank(address(usdc));
        reserve.claimRedeemedUSDC(1);
        assertFalse(usdc.callbackSucceeded());
        assertEq(usdc.balanceOf(address(usdc)), 31_500_000);
    }

    function testFuzzRedemptionSplittingAndOrder(uint96 rawAmount, uint96 rawSplit, uint16 rawPenalty) public {
        _seedReserve(10_000_003e6);
        _startRewards();
        uint256 amount = bound(rawAmount, 2, 100_000_000 ether);
        uint256 split = bound(rawSplit, 1, amount - 1);
        uint16 penalty = uint16(bound(rawPenalty, 0, 10_000));
        _reward(alice, amount);
        _reward(bob, amount);
        _open(penalty);
        _redeem(alice, split);
        _redeem(bob, amount);
        _redeem(alice, amount - split);
        (, uint256 aliceAccrued,) = reserve.requests(1, alice);
        (, uint256 bobAccrued,) = reserve.requests(1, bob);
        assertEq(aliceAccrued, bobAccrued);
        assertEq(
            aliceAccrued,
            amount * (10_000 - penalty) * usdc.balanceOf(address(reserve)) / (1_000_000_000 ether * 10_000)
        );
        assertLe(reserve.outstandingUSDC(), usdc.balanceOf(address(reserve)));
        assertEq(token.totalSupply(), 1_000_000_000 ether - 2 * amount);
    }
}
