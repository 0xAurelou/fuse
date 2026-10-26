// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {LPShareVault, ILPCapitalRewards} from "../src/LPShareVault.sol";
import {LPIncentiveDistributor} from "../src/LPIncentiveDistributor.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {LPModelVectors} from "./fixtures/LPModelVectors.sol";

/// Real contract states compared to independently generated Python expectations.
contract LPModelDifferentialTest is FUSEFixture {
    LPShareVault shares;
    LPIncentiveDistributor incentives;

    function setUp() public {
        _deploy();
        shares = lp.shareVault();
        access.grantRole(access.GUARDIAN(), address(controller));
        incentives = new LPIncentiveDistributor(access, token, shares);
        shares.setIncentives(ILPCapitalRewards(address(incentives)));
        token.lpEmissionEscrow().setDistributor(address(incentives));
        access.grantRole(access.LP_REWARD_PUBLISHER(), address(this));
        incentives.configureCampaign(uint64(block.timestamp), 2000);
        for (uint256 i; i < 2; ++i) {
            address owner = i == 0 ? alice : bob;
            access.grantRole(access.LP_PROVIDER(), owner);
            usdc.mint(owner, 1_000_000e6);
            vm.prank(owner);
            usdc.approve(address(shares), type(uint256).max);
        }
    }

    function _syncModel(int256 pnl, uint256 liability, uint256[] memory ids) private {
        if (access.tradingPaused()) access.resumeTrading();
        SettlementController.EpochSettlement memory report = _report(pnl, liability, ids);
        report.reportedRequiredLPCapitalUSDC = 100e6;
        bytes32 digest = controller.hashSettlement(report);
        controller.settleAndPause(report, ids, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _expectRow(uint256 n) private view {
        uint256[13] memory a = LPModelVectors.row(n);
        assertEq(lp.accountedBalance(), a[0], "cash");
        assertEq(lp.totalLPAssets(), a[1], "equity");
        assertEq(lp.reserveFeeAccruedUSDC(), a[2], "fee");
        assertEq(lp.reservedExitUSDC(), a[3], "claimable exits");
        assertEq(usdc.balanceOf(address(reserve)), a[4], "funded backing");
        assertEq(shares.totalSupply(), a[5], "share supply");
        assertEq(lp.cumulativeRealizedProfitUSDC(), int256(a[6]), "profit");
        assertEq(lp.highWaterAssets(), a[7], "HWM assets");
        assertEq(lp.highWaterShares(), a[8], "HWM shares");
        assertEq(incentives.totalPublishedBudget(), a[9], "published");
        assertEq(incentives.totalClaimed(), a[10], "claimed");
        assertEq(incentives.capitalSeconds(1), a[11], "capital seconds");
        assertEq(incentives.cumulativeIndex(), a[12], "reward index");
    }

    function testPythonProjectionMatchesRealContractTransitions() public {
        _syncModel(0, 0, new uint256[](0));
        shares.setPhase(LPShareVault.Phase.Whitelisted);
        LPShareVault.CapacityAuthorization memory cap = LPShareVault.CapacityAuthorization(
            controller.latestEpoch(), controller.currentRoot(), 1_000_000e6, 1, block.timestamp + 1 hours
        );
        bytes32 digest = shares.hashCapacity(cap);
        shares.publishCapacity(cap, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
        _syncModel(0, 0, new uint256[](0));
        _expectRow(0);
        vm.prank(alice);
        shares.deposit(123_456_789, alice);
        _expectRow(1);
        access.resumeTrading();
        uint256 id = custody.deposit(2000e6, alice);
        _syncModel(-2000e6, 0, _ids(id));
        _expectRow(2);
        _syncModel(1000e6, 1000e6, new uint256[](0));
        _expectRow(3);
        uint256 pendingShares = shares.balanceOf(alice) / 2;
        vm.prank(alice);
        uint256 request = shares.requestRedeem(pendingShares, alice, alice);
        vm.prank(bob);
        shares.deposit(321e6, bob);
        _expectRow(4);
        vm.warp(1_700_000_000 + 1 days);
        incentives.checkpointGlobal();
        LPIncentiveDistributor.UtilizationReport memory r = LPIncentiveDistributor.UtilizationReport(
            1, incentives.capitalSeconds(1) / 7, keccak256("differential utilization"), block.timestamp + 1 hours
        );
        access.resumeTrading();
        digest = incentives.hashUtilization(r);
        incentives.publishEpoch(r, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
        _expectRow(5);
        vm.warp(1_700_000_000 + 2 days);
        _syncModel(0, 1000e6, new uint256[](0));
        access.resumeTrading();
        _fundReserve(lp.reserveFeeAccruedUSDC());
        // Resume invalidated the old window; settleAndPause creates a new one.
        _syncModel(0, 1000e6, new uint256[](0));
        shares.fulfillRedeem(request);
        _expectRow(6);
        uint256 partialShares = shares.maxRedeem(alice) / 3;
        vm.prank(alice);
        shares.redeem(partialShares, alice, alice);
        _expectRow(7);
        uint256 remaining = shares.maxWithdraw(alice);
        vm.prank(alice);
        shares.withdraw(remaining, alice, alice);
        _expectRow(8);
        vm.warp(1_700_000_000 + 31 days);
        incentives.claim(1, alice);
        incentives.claim(1, bob);
        _expectRow(9);
        assertEq(token.totalSupply(), 1_000_000_000 ether);
    }

    function testAllNinetyEpochCapsMatchPython() public view {
        uint256 sum;
        for (uint64 i = 1; i <= 90; ++i) {
            assertEq(incentives.scheduledBudget(i), LPModelVectors.budget(i));
            sum += LPModelVectors.budget(i);
        }
        assertEq(sum, 50_000_000 ether);
        assertEq(incentives.scheduledBudget(0), 0);
        assertEq(incentives.scheduledBudget(91), 0);
    }
}
