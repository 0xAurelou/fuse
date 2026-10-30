// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {LPShareVault} from "../src/LPShareVault.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {Module} from "../src/common/Module.sol";

/// Regressions for unsolicited controller-slot occupation and owner/controller accounting.
contract LPControllerGriefTest is FUSEFixture {
    LPShareVault private shares;

    function setUp() public {
        _deploy();
        shares = lp.shareVault();
        access.grantRole(access.GUARDIAN(), address(controller));
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
        vm.prank(alice);
        shares.deposit(100_000e6, alice);
    }

    function _sync() private {
        if (access.tradingPaused()) access.resumeTrading();
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory r = _report(0, custody.customerLiabilityUSDC(), ids);
        bytes32 digest = controller.hashSettlement(r);
        controller.settleAndPause(r, ids, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _capacity() private {
        LPShareVault.CapacityAuthorization memory a = LPShareVault.CapacityAuthorization(
            controller.latestEpoch(),
            controller.currentRoot(),
            1_000_000e6,
            shares.capacityNonce() + 1,
            block.timestamp + 1 hours
        );
        bytes32 digest = shares.hashCapacity(a);
        shares.publishCapacity(a, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _enterBob(uint256 assets) private returns (uint256) {
        vm.prank(bob);
        return shares.deposit(assets, bob);
    }

    function testDustCannotOccupyVictimSlotOrBlockLegacyExit() public {
        _enterBob(1);
        uint256 supply = shares.totalSupply();
        vm.prank(bob);
        vm.expectRevert(LPShareVault.InvalidRequest.selector);
        shares.requestRedeem(1, alice, bob);
        assertEq(shares.activeRequest(alice), 0);
        assertEq(shares.activeRequest(bob), 0);
        assertEq(shares.controllerRequest(alice), 0);
        assertEq(shares.nextRequestId(), 1);
        assertEq(shares.totalSupply(), supply);
        assertEq(shares.balanceOf(address(shares)), 0);

        vm.prank(alice);
        uint256 id = lp.requestLPExit();
        vm.warp(block.timestamp + shares.EXIT_DELAY());
        _sync();
        shares.fulfillRedeem(id);
        vm.prank(alice);
        assertEq(lp.executeLPExit(), 100_000e6);
        assertEq(shares.activeRequest(alice), 0);
        assertEq(shares.controllerRequest(alice), 0);
    }

    function testFullSizeRequestRequiresOwnerApprovalOfController() public {
        uint256 amount = _enterBob(10e6);
        // Even a controller consenting to the requester needs the owner's approval.
        vm.prank(alice);
        shares.setOperator(bob, true);
        vm.prank(bob);
        vm.expectRevert(Module.Unauthorized.selector);
        shares.requestRedeem(amount, alice, bob);
        assertEq(shares.activeRequest(alice), 0);
        assertEq(shares.controllerRequest(alice), 0);
        vm.prank(alice);
        shares.requestRedeem(1 ether, alice, alice);
    }

    function testUnilateralOperatorApprovalCannotOccupyVictimSlot() public {
        uint256 amount = _enterBob(10e6);
        vm.prank(bob);
        shares.setOperator(alice, true);
        vm.prank(bob);
        vm.expectRevert(Module.Unauthorized.selector);
        shares.requestRedeem(amount, alice, bob);
        assertEq(shares.activeRequest(bob), 0);
        assertEq(shares.controllerRequest(alice), 0);
        assertEq(shares.nextRequestId(), 1);
        vm.prank(alice);
        shares.requestRedeem(1 ether, alice, alice);
    }

    function testMinimumRequestRejectsDustAndAcceptsOneUSDC() public {
        uint256 minimum = shares.minRedeemShares();
        assertEq(minimum, 1 ether);
        vm.startPrank(alice);
        vm.expectRevert(LPShareVault.InvalidRequest.selector);
        shares.requestRedeem(minimum - 1, alice, alice);
        uint256 id = shares.requestRedeem(minimum, alice, alice);
        vm.stopPrank();
        assertEq(shares.pendingRedeemRequest(id, alice), minimum);
    }

    function testFuzzMinimumUsesAccountedNAV(uint64 rawLoss) public {
        uint256 loss = bound(rawLoss, 1, 500_000e6);
        access.resumeTrading();
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory r = _report(int256(loss), loss, ids);
        bytes32 digest = controller.hashSettlement(r);
        controller.settleAndPause(r, ids, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
        uint256 minimum = shares.minRedeemShares();
        assertGt(minimum, 1 ether);
        assertLt(shares.convertToAssets(minimum - 1), shares.MIN_REDEEM_ASSETS());
        assertGe(shares.convertToAssets(minimum), shares.MIN_REDEEM_ASSETS());
        vm.startPrank(alice);
        vm.expectRevert(LPShareVault.InvalidRequest.selector);
        shares.requestRedeem(minimum - 1, alice, alice);
        shares.requestRedeem(minimum, alice, alice);
        vm.stopPrank();
    }

    function testOperatorCanRequestAndClaimForConsentingOwner() public {
        vm.prank(alice);
        shares.setOperator(bob, true);
        vm.prank(bob);
        uint256 id = shares.requestRedeem(2 ether, alice, alice);
        vm.warp(block.timestamp + shares.EXIT_DELAY());
        _sync();
        shares.fulfillRedeem(id);
        vm.prank(bob);
        assertEq(shares.redeem(2 ether, alice, alice), 2e6);
        assertEq(shares.activeRequest(alice), 0);
        assertEq(shares.controllerRequest(alice), 0);
    }

    function testAllowanceSpenderCanRequestButCannotRedirectController() public {
        vm.prank(alice);
        shares.approve(bob, 2 ether);
        vm.prank(bob);
        vm.expectRevert(Module.Unauthorized.selector);
        shares.requestRedeem(2 ether, bob, alice);
        assertEq(shares.allowance(alice, bob), 2 ether);
        vm.prank(bob);
        uint256 id = shares.requestRedeem(2 ether, alice, alice);
        assertEq(shares.allowance(alice, bob), 0);
        assertEq(shares.activeRequest(alice), id);
    }

    function testDelegatedControllerClaimsClearTheOwnersSlot() public {
        vm.prank(alice);
        shares.setOperator(bob, true);
        // Bob accepts the controller role by submitting the request himself.
        vm.prank(bob);
        uint256 id = shares.requestRedeem(3 ether, bob, alice);
        assertEq(shares.activeRequest(alice), id);
        assertEq(shares.activeRequest(bob), 0);
        assertEq(shares.controllerRequest(bob), id);
        assertEq(shares.controllerRequest(alice), 0);
        assertEq(shares.pendingRedeemRequest(id, bob), 3 ether);
        assertEq(shares.pendingRedeemRequest(id, alice), 0);

        // Changing controllers cannot create a second request against the same owner.
        vm.prank(alice);
        vm.expectRevert(LPShareVault.InvalidRequest.selector);
        shares.requestRedeem(1 ether, alice, alice);
        vm.warp(block.timestamp + shares.EXIT_DELAY());
        _sync();
        shares.fulfillRedeem(id);
        assertEq(shares.maxRedeem(bob), 3 ether);
        assertEq(shares.maxWithdraw(bob), 3e6);
        assertEq(shares.maxRedeem(alice), 0);
        assertEq(shares.claimableRedeemRequest(id, bob), 3 ether);

        // Neither being the owner nor the legacy helper overrides controller rights.
        vm.prank(alice);
        vm.expectRevert(Module.Unauthorized.selector);
        shares.redeem(3 ether, alice, bob);
        vm.prank(alice);
        vm.expectRevert(LPShareVault.InvalidRequest.selector);
        lp.executeLPExit();

        vm.prank(bob);
        assertEq(shares.redeem(1 ether, alice, bob), 1e6);
        assertEq(shares.activeRequest(alice), id);
        assertEq(shares.controllerRequest(bob), id);
        vm.prank(bob);
        assertEq(shares.withdraw(2e6, alice, bob), 2 ether);
        assertEq(shares.activeRequest(alice), 0);
        assertEq(shares.controllerRequest(bob), 0);
        assertEq(shares.claimableRedeemRequest(id, bob), 0);
        assertEq(lp.reservedExitUSDC(), 0);

        vm.prank(alice);
        shares.requestRedeem(1 ether, alice, alice);
    }

    function testOwnerMaySubmitForControllerWhoApprovesThem() public {
        vm.prank(alice);
        shares.setOperator(bob, true);
        vm.prank(bob);
        shares.setOperator(alice, true);
        vm.prank(alice);
        uint256 id = shares.requestRedeem(1 ether, bob, alice);
        assertEq(shares.activeRequest(alice), id);
        assertEq(shares.controllerRequest(bob), id);
    }

    function testSharedControllerCannotOverwriteAnotherOwnersClaim() public {
        _enterBob(10e6);
        vm.prank(alice);
        shares.setOperator(bob, true);
        vm.prank(bob);
        uint256 id = shares.requestRedeem(1 ether, bob, alice);
        vm.prank(bob);
        vm.expectRevert(LPShareVault.InvalidRequest.selector);
        shares.requestRedeem(1 ether, bob, bob);
        assertEq(shares.activeRequest(alice), id);
        assertEq(shares.activeRequest(bob), 0);
        assertEq(shares.controllerRequest(bob), id);
        assertEq(shares.nextRequestId(), id + 1);
    }
}
