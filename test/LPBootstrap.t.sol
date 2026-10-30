// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {LPShareVault, ILPCapitalRewards} from "../src/LPShareVault.sol";
import {LPIncentiveDistributor} from "../src/LPIncentiveDistributor.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {LPBootstrapVectors} from "./fixtures/LPBootstrapVectors.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

contract LPBootstrapTest is FUSEFixture {
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
        for (uint256 i; i < 2; ++i) {
            address owner = i == 0 ? alice : bob;
            access.grantRole(access.LP_PROVIDER(), owner);
            usdc.mint(owner, 10_000_000e6);
            vm.prank(owner);
            usdc.approve(address(shares), type(uint256).max);
        }
        _sync();
        shares.setPhase(LPShareVault.Phase.Whitelisted);
        _capacity();
        _sync();
        _deposit(alice, 100_000e6);
    }

    function _sync() private {
        if (access.tradingPaused()) access.resumeTrading();
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory r = _report(0, custody.customerLiabilityUSDC(), ids);
        bytes32 digest = controller.hashSettlement(r);
        controller.settleAndPause(r, ids, _sign(SETTLEMENT_KEY,digest), _sign(RISK_KEY,digest));
    }

    function _capacity() private {
        LPShareVault.CapacityAuthorization memory a = LPShareVault.CapacityAuthorization(
            controller.latestEpoch(),controller.currentRoot(),1_000_000e6,shares.capacityNonce()+1,block.timestamp+1 hours
        );
        bytes32 digest = shares.hashCapacity(a);
        shares.publishCapacity(a,_sign(SETTLEMENT_KEY,digest),_sign(RISK_KEY,digest));
    }

    function _deposit(address owner, uint256 amount) private {
        vm.prank(owner);
        shares.deposit(amount,owner);
    }

    function _publish(uint64 epoch) private {
        incentives.checkpointGlobal();
        LPIncentiveDistributor.UtilizationReport memory r = LPIncentiveDistributor.UtilizationReport(
            epoch,incentives.capitalSeconds(epoch)/5,keccak256(abi.encode("bootstrap synthetic liability journal",epoch)),block.timestamp+1 hours
        );
        bytes32 digest = incentives.hashUtilization(r);
        if (access.tradingPaused()) access.resumeTrading();
        incentives.publishEpoch(r,_sign(SETTLEMENT_KEY,digest),_sign(RISK_KEY,digest));
    }

    function _expectVector(uint256 n) private {
        uint256[4] memory row = LPBootstrapVectors.row(n);
        assertEq(incentives.capitalSeconds(1),row[0],"capital-time denominator");
        (,uint256 liabilitySeconds,,,) = incentives.epochs(1);
        assertEq(liabilitySeconds,row[1],"liability time");
        uint256 earnedAlice = incentives.earned(1,alice);
        uint256 earnedBob = incentives.earned(1,bob);
        // Two conservative index roundings and one account rounding can lose
        // dust. The exact rational vector is an upper bound, never exceeded.
        assertLe(earnedAlice,row[2]);
        assertLe(earnedBob,row[3]);
        assertLe(row[2]-earnedAlice,5_000_000_000);
        assertLe(row[3]-earnedBob,5_000_000_000);
        assertEq(incentives.earned(1,address(this)),0,"protocol exclusion");
        assertEq(incentives.earned(1,address(shares)),0,"queued exclusion");
    }

    function testBootstrapConstantCapitalMatchesRationalReferenceAndLegacyStillAvailable() public {
        assertFalse(incentives.bootstrapCampaign());
        incentives.configureBootstrapCampaign(uint64(block.timestamp),2000);
        assertTrue(incentives.bootstrapCampaign());
        assertEq(incentives.bootstrapFactor(),uint256(1e27)*1_900_000/2_750_000);
        vm.warp(block.timestamp+1 days);
        _publish(1);
        _expectVector(0);
        vm.expectRevert();
        incentives.configureCampaign(uint64(block.timestamp),2000);
        vm.expectRevert();
        incentives.configureBootstrapCampaign(uint64(block.timestamp),2000);
    }

    function testCrossingThreeMillionCannotRepriceEarlierHalfDay() public {
        uint64 start = uint64(block.timestamp);
        incentives.configureBootstrapCampaign(start,2000);
        vm.warp(start+12 hours);
        _sync(); _capacity();
        _deposit(bob,1_900_000e6);
        assertEq(shares.totalAssets(),3_000_000e6);
        assertEq(incentives.bootstrapFactor(),0);
        vm.warp(start+1 days);
        _publish(1);
        _expectVector(1);
        uint256 accrued = incentives.earned(1,alice);
        vm.warp(start+31 days);
        access.pauseTrading();
        assertEq(incentives.claim(1,alice),accrued,"threshold and pause preserve past claim");
        vm.expectRevert();
        incentives.claim(1,alice);
    }

    function testRequestedExitStopsNewScoreButDoesNotCancelEarlierRights() public {
        uint64 start = uint64(block.timestamp);
        incentives.configureBootstrapCampaign(start,2000);
        vm.warp(start+12 hours);
        uint256 balance = shares.balanceOf(alice);
        vm.prank(alice);
        uint256 request = shares.requestRedeem(balance,alice,alice);
        vm.warp(start+1 days);
        _publish(1);
        _expectVector(2);
        uint256 accrued = incentives.earned(1,alice);
        vm.warp(start+60 hours);
        _sync();
        shares.fulfillRedeem(request);
        uint256 withdrawable = shares.maxWithdraw(alice);
        vm.prank(alice);
        shares.withdraw(withdrawable,alice,alice);
        vm.warp(start+31 days);
        assertEq(incentives.claim(1,alice),accrued,"vested reward survives full capital exit");
    }

    function testMidDayDepositSharesOnlyItsOwnTaperedTime() public {
        uint64 start = uint64(block.timestamp);
        incentives.configureBootstrapCampaign(start,2000);
        vm.warp(start+12 hours);
        _sync(); _capacity();
        _deposit(bob,500_000e6);
        vm.warp(start+1 days);
        _publish(1);
        _expectVector(3);
    }

    function testAtThresholdNoRewardsAndWithdrawalResumesOnlyOriginalCampaign() public {
        _deposit(bob,1_900_000e6);
        uint64 start = uint64(block.timestamp);
        incentives.configureBootstrapCampaign(start,2000);
        uint256 balance = shares.balanceOf(bob);
        vm.prank(bob);
        uint256 request = shares.requestRedeem(balance,bob,bob);
        vm.warp(start+1 days);
        _publish(1);
        assertEq(incentives.earned(1,alice),0);
        assertEq(incentives.earned(1,bob),0);
        vm.warp(start+2 days);
        _sync();
        shares.fulfillRedeem(request);
        assertEq(shares.totalAssets(),1_100_000e6);
        assertGt(incentives.bootstrapFactor(),0);
        assertEq(incentives.end(),start+90 days,"withdrawal cannot extend campaign");
        vm.warp(start+3 days);
        _publish(3);
        assertGt(incentives.earned(3,alice),0,"later below-threshold interval resumes");
        assertEq(incentives.earned(3,bob),0,"exited capital cannot earn");
    }

    function testBootstrapConfigurationAndIdleLiabilityAreEnforced() public {
        vm.prank(alice);
        vm.expectRevert();
        incentives.configureBootstrapCampaign(uint64(block.timestamp),2000);
        incentives.configureBootstrapCampaign(uint64(block.timestamp),2000);
        vm.warp(block.timestamp+1 days);
        LPIncentiveDistributor.UtilizationReport memory r = LPIncentiveDistributor.UtilizationReport(
            1,0,keccak256("no accepted liability"),block.timestamp+1 hours
        );
        bytes32 digest = incentives.hashUtilization(r);
        access.resumeTrading();
        incentives.publishEpoch(r,_sign(SETTLEMENT_KEY,digest),_sign(RISK_KEY,digest));
        assertEq(incentives.earned(1,alice),0);
        assertEq(incentives.totalPublishedBudget(),0);
    }

    function testBootstrapFullRateBoundaryUsesUnderwritingEquityAfterLoss() public {
        incentives.configureBootstrapCampaign(uint64(block.timestamp),2000);
        vm.warp(block.timestamp+1 hours);
        if (access.tradingPaused()) access.resumeTrading();
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory r = _report(850_000e6,850_000e6,ids);
        bytes32 digest = controller.hashSettlement(r);
        controller.settleAndPause(r,ids,_sign(SETTLEMENT_KEY,digest),_sign(RISK_KEY,digest));
        assertEq(shares.totalAssets(),250_000e6);
        assertEq(incentives.bootstrapFactor(),1e27);
        assertEq(usdc.balanceOf(address(reserve)),0,"no backing used to repair LP loss");
    }

    function testFuzzDepositsCannotExceedRationalTaperedEntitlement(uint64 rawAmount,uint32 rawSeconds) public {
        uint256 amount = bound(rawAmount,1,2_000_000e6);
        uint256 elapsed = bound(rawSeconds,0,1 days);
        uint64 start = uint64(block.timestamp);
        incentives.configureBootstrapCampaign(start,2000);
        vm.warp(start+elapsed);
        _sync(); _capacity();
        _deposit(bob,amount);
        vm.warp(start+1 days);
        _publish(1);
        uint256 e0 = 1_100_000e6;
        uint256 e1 = e0+amount;
        uint256 range = 2_750_000e6;
        uint256 gap0 = 3_000_000e6-e0;
        uint256 gap1 = e1 < 3_000_000e6 ? 3_000_000e6-e1 : 0;
        uint256 capital = e0*elapsed+e1*(1 days-elapsed);
        uint256 aliceNumerator = 100_000e6*(gap0*elapsed+gap1*(1 days-elapsed));
        uint256 bobNumerator = amount*gap1*(1 days-elapsed);
        uint256 cap = incentives.scheduledBudget(1);
        uint256 expectedAlice = Math.mulDiv(cap,aliceNumerator,capital*range);
        uint256 expectedBob = Math.mulDiv(cap,bobNumerator,capital*range);
        uint256 actualAlice = incentives.earned(1,alice);
        uint256 actualBob = incentives.earned(1,bob);
        assertEq(incentives.capitalSeconds(1),capital);
        assertLe(actualAlice,expectedAlice);
        assertLe(actualBob,expectedBob);
        assertLe(expectedAlice-actualAlice,5_000_000_000);
        assertLe(expectedBob-actualBob,5_000_000_000);
        assertLe(actualAlice+actualBob,cap);
    }
}
