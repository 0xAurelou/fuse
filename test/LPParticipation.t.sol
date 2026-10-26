// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {LPShareVault, ILPCapitalRewards} from "../src/LPShareVault.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {LPVault} from "../src/LPVault.sol";
import {LPIncentiveDistributor} from "../src/LPIncentiveDistributor.sol";
import {AccessController} from "../src/AccessController.sol";
import {FUSEToken} from "../src/FUSEToken.sol";

contract LPParticipationTest is FUSEFixture {
    LPShareVault private shares;
    LPIncentiveDistributor private incentives;

    function setUp() public {
        _deploy();
        shares = lp.shareVault();
        access.grantRole(access.GUARDIAN(), address(controller));
        incentives = new LPIncentiveDistributor(access, token, shares);
        shares.setIncentives(ILPCapitalRewards(address(incentives)));
        token.lpEmissionEscrow().setDistributor(address(incentives));
        access.grantRole(access.LP_REWARD_PUBLISHER(), address(this));
        usdc.mint(alice, 10_000_000e6);
        usdc.mint(bob, 10_000_000e6);
        vm.prank(alice);
        usdc.approve(address(shares), type(uint256).max);
        vm.prank(bob);
        usdc.approve(address(shares), type(uint256).max);
    }

    function _settleLP(int256 pnl, uint256 liability, uint256[] memory ids) private {
        _submitLP(_report(pnl, liability, ids), ids);
    }

    function _submitLP(SettlementController.EpochSettlement memory report, uint256[] memory ids) private {
        if (access.tradingPaused()) access.resumeTrading();
        if (report.reportedMaxOpenExposureUSDC == 0 && shares.phase() != LPShareVault.Phase.Protocol) {
            bytes32 digest = controller.hashSettlement(report);
            controller.settleAndPause(report, ids, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
        } else {
            _submit(report, ids);
        }
    }

    function _sync() private {
        _settleLP(0, custody.customerLiabilityUSDC(), new uint256[](0));
    }

    function _capacity(uint256 demand) private {
        LPShareVault.CapacityAuthorization memory a = LPShareVault.CapacityAuthorization({
            epoch: controller.latestEpoch(),
            checkpointRoot: controller.currentRoot(),
            eligibleDemandUSDC: demand,
            nonce: shares.capacityNonce() + 1,
            deadline: block.timestamp + 1 hours
        });
        bytes32 digest = shares.hashCapacity(a);
        shares.publishCapacity(a, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _open() private {
        _sync();
        access.grantRole(access.LP_PROVIDER(), alice);
        shares.setPhase(LPShareVault.Phase.Whitelisted);
        _capacity(1_000_000e6);
        _sync();
    }

    function _enter(address account, uint256 amount) private returns (uint256 minted) {
        vm.prank(account);
        minted = shares.deposit(amount, account);
    }

    function _request(address account, uint256 amount) private returns (uint256 id) {
        vm.prank(account);
        id = shares.requestRedeem(amount, account, account);
    }

    function _profit(uint256 amount) private {
        bool paused = access.tradingPaused();
        if (paused) access.resumeTrading();
        uint256 id = custody.deposit(amount, alice);
        _settleLP(-int256(amount), custody.customerLiabilityUSDC(), _ids(id));
    }

    function _publish(uint64 epoch, uint256 liabilitySeconds) private {
        LPIncentiveDistributor.UtilizationReport memory r = LPIncentiveDistributor.UtilizationReport({
            epoch: epoch,
            liabilitySeconds: liabilitySeconds,
            journalHash: keccak256(abi.encode(epoch, "actual underwriting journal")),
            deadline: block.timestamp + 1 hours
        });
        bytes32 digest = incentives.hashUtilization(r);
        bool paused = access.tradingPaused();
        if (paused) access.resumeTrading();
        incentives.publishEpoch(r, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
        if (paused) access.pauseTrading();
    }

    function testGenesisReallocationAndLegacySeedOwnsEquity() public view {
        assertEq(token.totalSupply(), 1_000_000_000 ether);
        assertEq(token.balanceOf(address(token.lpEmissionEscrow())), 50_000_000 ether);
        assertEq(token.balanceOf(address(token.treasuryEscrow())), 350_000_000 ether);
        assertEq(shares.balanceOf(address(this)), 1_000_000 ether);
        assertEq(shares.totalAssets(), 1_000_000e6);
        assertTrue(shares.protocolCapital(address(this)));
        assertEq(shares.decimals(), 18);
        assertEq(shares.asset(), address(usdc));
    }

    function testLaunchGatesCapacityExpiryAndPublicPhase() public {
        assertEq(shares.maxDeposit(alice), 0);
        _open();
        assertEq(shares.maxDeposit(bob), 0);
        _capacity(200_000e6);
        assertEq(shares.maxDeposit(alice), 0); // $1m of usable equity already fills demand cap.
        _capacity(220_000e6);
        assertEq(shares.maxDeposit(alice), 100_000e6);
        _enter(alice, 100_000e6);
        assertEq(shares.maxDeposit(alice), 0);
        vm.warp(block.timestamp + 1 hours + 1);
        assertEq(shares.maxDeposit(alice), 0);
        _sync();
        shares.setPhase(LPShareVault.Phase.Public);
        _capacity(500_000e6);
        assertGt(shares.maxDeposit(bob), 0);
        _enter(bob, 10_000e6);
        vm.expectRevert();
        shares.setPhase(LPShareVault.Phase.Protocol);
    }

    function testDonationDoesNotInflateShareNAV() public {
        _open();
        uint256 before = shares.previewDeposit(100e6);
        usdc.transfer(address(lp), 1_000_000e6);
        assertEq(shares.previewDeposit(100e6), before);
        assertEq(_enter(alice, 100e6), before);
    }

    function testLegacyDepositCallbackCannotTemporarilyDilutePendingExit() public {
        _open();
        uint256 minted = _enter(alice, 100_000e6);
        uint256 id = _request(alice, minted);
        vm.warp(block.timestamp + 48 hours);
        _sync();
        _capacity(1_000_000e6);
        access.grantRole(access.LP_PROVIDER(), bob);
        usdc.setCallback(address(shares), abi.encodeCall(shares.fulfillRedeem, (id)));
        vm.startPrank(bob);
        usdc.approve(address(lp), type(uint256).max);
        lp.depositLP(100_000e6);
        vm.stopPrank();
        assertTrue(usdc.callbackSucceeded());
        assertEq(shares.maxWithdraw(alice), 100_000e6);
        assertEq(shares.balanceOf(bob), 100_000 ether);
        assertEq(lp.totalLPAssets() + lp.reservedExitUSDC(), lp.accountedBalance());
    }

    function testOnlyAtomicLiquidityWindowAllowsExternalEntry() public {
        _open();
        uint256 nonce = access.pauseNonce();
        assertGt(shares.maxDeposit(alice), 0);
        // Even in the same block, resuming and pausing invalidates the old window.
        access.resumeTrading();
        access.pauseTrading();
        assertGt(access.pauseNonce(), nonce);
        assertEq(shares.maxDeposit(alice), 0);
        access.resumeTrading();
        _settle(0, 0, new uint256[](0));
        access.pauseTrading(); // A generic pause after a normal report is insufficient.
        assertEq(shares.maxDeposit(alice), 0);
        _sync();
        assertGt(shares.maxDeposit(alice), 0);
    }

    function testCapacityAndRewardsRequireIndependentRiskApproval() public {
        _open();
        LPShareVault.CapacityAuthorization memory a = LPShareVault.CapacityAuthorization(
            controller.latestEpoch(),
            controller.currentRoot(),
            1_000_000e6,
            shares.capacityNonce() + 1,
            block.timestamp + 1 hours
        );
        bytes memory signature = _sign(SETTLEMENT_KEY, shares.hashCapacity(a));
        vm.expectRevert();
        shares.publishCapacity(a, signature, signature);
        incentives.configureCampaign(uint64(block.timestamp), 2000);
        vm.warp(block.timestamp + 1 days);
        access.resumeTrading();
        LPIncentiveDistributor.UtilizationReport memory r = LPIncentiveDistributor.UtilizationReport(
            1, 1, keccak256("underwriting journal"), block.timestamp + 1 hours
        );
        signature = _sign(SETTLEMENT_KEY, incentives.hashUtilization(r));
        vm.expectRevert();
        incentives.publishEpoch(r, signature, signature);
        assertEq(incentives.totalPublishedBudget(), 0);
    }

    function testSettledDrawdownIgnoresFairNAVContributions() public {
        _open();
        _settleLP(100_000e6, 100_000e6, new uint256[](0));
        uint16 drawdown = lp.maxDrawdownBps();
        assertApproxEqAbs(drawdown, 1000, 1);
        _capacity(1_000_000e6);
        _enter(alice, 100_000e6);
        _sync();
        assertEq(lp.maxDrawdownBps(), drawdown);
        _settleLP(-100_000e6, 0, new uint256[](0));
        assertEq(lp.maxDrawdownBps(), drawdown);
    }

    function testLPFirstWaterfallAndNoNewSupply() public {
        _open();
        _profit(200_000e6);
        assertEq(lp.reserveFeeAccruedUSDC(), 70_000e6);
        assertEq(shares.totalAssets(), 1_130_000e6);
        uint256 nav = shares.convertToAssets(1 ether);
        access.resumeTrading();
        _fundReserve(70_000e6);
        _sync();
        assertEq(shares.convertToAssets(1 ether), nav);
        assertEq(lp.reserveFeeAccruedUSDC(), 0);
        assertEq(usdc.balanceOf(address(reserve)), 70_000e6);
        assertEq(token.totalSupply(), 1_000_000_000 ether);
    }

    function testLossRecoveryAndCapitalContributionsDoNotResetHWM() public {
        _open();
        _profit(1000e6);
        access.resumeTrading();
        _fundReserve(350e6);
        _sync();
        _settleLP(500e6, 500e6, new uint256[](0));
        _capacity(1_000_000e6);
        _enter(alice, 100_000e6);
        _settleLP(-100e6, 400e6, new uint256[](0));
        assertEq(lp.reserveFeeAccruedUSDC(), 0);
        // All old losses must be recovered at the enlarged share supply's HWM.
        _settleLP(-400e6, 0, new uint256[](0));
        assertEq(lp.reserveFeeAccruedUSDC(), 0);
    }

    function testProtectedRetainedProfitNeverChargedAfterNewDeposits() public {
        _open();
        access.resumeTrading();
        uint256 id = custody.deposit(1000e6, alice);
        access.pauseTrading();
        uint256[] memory ids = _ids(id);
        SettlementController.EpochSettlement memory r = _report(-1000e6, 0, ids);
        r.reportedRequiredLPCapitalUSDC = 600_000e6;
        _submitLP(r, ids);
        assertEq(lp.reserveFeeAccruedUSDC(), 0);
        _capacity(1_000_000e6);
        _enter(alice, 1_000_000e6);
        _sync();
        assertEq(lp.reserveFeeAccruedUSDC(), 0);
        _profit(1000e6);
        assertLe(lp.reserveFeeAccruedUSDC(), 350e6);
    }

    function testAsyncExitDelayFreshNAVAndLossAtFulfillment() public {
        _open();
        uint256 minted = _enter(alice, 100_000e6);
        uint256 id = _request(alice, minted);
        assertEq(shares.balanceOf(alice), 0);
        assertEq(shares.pendingRedeemRequest(id, alice), minted);
        vm.expectRevert();
        shares.fulfillRedeem(id);
        vm.warp(block.timestamp + 48 hours);
        vm.expectRevert();
        shares.fulfillRedeem(id); // Cannot cash out at the pre-request checkpoint.
        _settleLP(110_000e6, 110_000e6, new uint256[](0));
        shares.fulfillRedeem(id);
        uint256 assets = shares.maxWithdraw(alice);
        assertApproxEqAbs(assets, 90_000e6, 1);
        assertEq(lp.reservedExitUSDC(), assets);
        assertEq(shares.claimableRedeemRequest(id, alice), minted);
        access.pauseTrading();
        vm.prank(alice);
        assertEq(shares.redeem(minted, alice, alice), assets);
        assertEq(lp.reservedExitUSDC(), 0);
        assertEq(shares.maxRedeem(alice), 0);
        assertEq(shares.activeRequest(alice), 0);
    }

    function testFIFOAndCapitalFloorCannotBeBypassed() public {
        _open();
        access.grantRole(access.LP_PROVIDER(), bob);
        uint256 a = _enter(alice, 100_000e6);
        uint256 b = _enter(bob, 100_000e6);
        uint256 first = _request(alice, a);
        uint256 second = _request(bob, b);
        vm.warp(block.timestamp + 48 hours);
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory r = _report(0, 0, ids);
        r.reportedRequiredLPCapitalUSDC = 560_000e6;
        _submitLP(r, ids);
        vm.expectRevert();
        shares.fulfillRedeem(second);
        vm.expectRevert();
        shares.fulfillRedeem(first);
        _sync();
        shares.fulfillRedeem(first);
        shares.fulfillRedeem(second);
    }

    function testOpenExposureBlocksNAVEntryAndExit() public {
        _open();
        uint256 minted = _enter(alice, 100e6);
        uint256 id = _request(alice, minted);
        vm.warp(block.timestamp + 48 hours);
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory r = _report(0, 0, ids);
        r.reportedRequiredLPCapitalUSDC = 100e6;
        r.reportedMaxOpenExposureUSDC = 50e6;
        _submitLP(r, ids);
        assertEq(shares.maxDeposit(alice), 0);
        vm.expectRevert(LPShareVault.NAVUnavailable.selector);
        shares.fulfillRedeem(id);
    }

    function testClaimableExitCannotUnderwriteOrBeRedirectedWithoutConsent() public {
        _open();
        uint256 minted = _enter(alice, 100e6);
        uint256 id = _request(alice, minted);
        vm.warp(block.timestamp + 48 hours);
        _sync();
        shares.fulfillRedeem(id);
        uint256 assets = shares.maxWithdraw(alice);
        assertEq(lp.totalLPAssets() + lp.reservedExitUSDC(), lp.accountedBalance());
        vm.prank(bob);
        vm.expectRevert();
        shares.redeem(minted, bob, alice);
        vm.prank(alice);
        shares.setOperator(bob, true);
        vm.prank(bob);
        shares.withdraw(assets, alice, alice);
        assertEq(lp.reservedExitUSDC(), 0);
        assertEq(usdc.balanceOf(alice), 10_000_000e6);
    }

    function testInterfacesAndAsyncPreviews() public view {
        assertTrue(shares.supportsInterface(0x620ee8e4));
        assertTrue(shares.supportsInterface(0xe3bc4e65));
        assertTrue(shares.supportsInterface(0x2f0a18c5));
        assertFalse(shares.supportsInterface(0xce3bbe50));
        assertEq(shares.share(), address(shares));
    }

    function testPreviewsAndSharesCannotBypassQueue() public {
        vm.expectRevert(LPShareVault.AsyncPreview.selector);
        shares.previewRedeem(1);
        vm.expectRevert(LPShareVault.AsyncPreview.selector);
        shares.previewWithdraw(1);
        vm.expectRevert(LPShareVault.NonTransferableShares.selector);
        shares.transfer(alice, 1);
    }

    function testIncentivesIdleCapitalGetsZeroAndSlotsExpire() public {
        _open();
        _enter(alice, 100_000e6);
        incentives.configureCampaign(uint64(block.timestamp), 2000);
        vm.warp(block.timestamp + 1 days);
        _publish(1, 0);
        assertEq(incentives.totalPublishedBudget(), 0);
        vm.warp(incentives.end() + 1 days);
        LPIncentiveDistributor.UtilizationReport memory r =
            LPIncentiveDistributor.UtilizationReport(90, 1, bytes32(uint256(1)), block.timestamp + 1);
        bytes32 digest = incentives.hashUtilization(r);
        bytes memory s = _sign(SETTLEMENT_KEY, digest);
        bytes memory k = _sign(RISK_KEY, digest);
        vm.expectRevert();
        incentives.publishEpoch(r, s, k);
    }

    function testRewardsCapitalTimeVestingProtocolAndPendingExclusion() public {
        _open();
        _enter(alice, 100_000e6);
        incentives.configureCampaign(uint64(block.timestamp), 2000);
        vm.warp(block.timestamp + 12 hours);
        uint256 id = _request(alice, shares.balanceOf(alice) / 2);
        vm.warp(block.timestamp + 12 hours);
        _publish(1, 1_100_000e6 * 1 days / 5);
        uint256 earned = incentives.earned(1, alice);
        uint256 expected = incentives.scheduledBudget(1) * (75_000e6 * 1 days) / (1_100_000e6 * 1 days);
        assertApproxEqAbs(earned, expected, 1000);
        assertEq(incentives.earned(1, address(this)), 0);
        assertEq(incentives.earned(1, address(shares)), 0);
        vm.expectRevert();
        incentives.claim(1, alice);
        vm.warp(block.timestamp + 30 days);
        assertEq(incentives.claim(1, alice), earned);
        assertEq(token.balanceOf(alice), earned);
        assertFalse(token.transfersEnabled());
        vm.expectRevert();
        incentives.claim(1, alice);
        assertGt(shares.pendingRedeemRequest(id, alice), 0);
    }

    function testNinetyDayBudgetDeclinesAndIsBounded() public view {
        uint256 total;
        uint256 previous = type(uint256).max;
        for (uint64 i = 1; i <= 90; ++i) {
            uint256 budget = incentives.scheduledBudget(i);
            assertLe(budget, previous);
            previous = budget;
            total += budget;
        }
        assertEq(total, 50_000_000 ether);
        assertEq(incentives.scheduledBudget(91), 0);
    }

    function testFuzzPartialClaimCannotIncreaseExitPayout(uint64 rawAssets, uint64 rawSplit) public {
        uint256 assets = bound(rawAssets, 1, 10_000e6);
        _open();
        uint256 minted = _enter(alice, assets);
        uint256 id = _request(alice, minted);
        vm.warp(block.timestamp + 48 hours);
        _sync();
        shares.fulfillRedeem(id);
        uint256 due = shares.maxWithdraw(alice);
        uint256 split = bound(rawSplit, 1, minted - 1);
        vm.startPrank(alice);
        uint256 first = shares.redeem(split, alice, alice);
        uint256 second = shares.redeem(minted - split, alice, alice);
        vm.stopPrank();
        assertEq(first + second, due);
        assertEq(lp.reservedExitUSDC(), 0);
    }
}
