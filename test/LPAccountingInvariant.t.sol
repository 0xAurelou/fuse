// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {StdInvariant} from "forge-std/StdInvariant.sol";
import {Test} from "forge-std/Test.sol";
import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {LPShareVault} from "../src/LPShareVault.sol";
import {SettlementController} from "../src/SettlementController.sol";

/// @dev Mixed external-LP transitions at truthful, zero-exposure settlement boundaries.
contract LPAccountingHandler is FUSEFixture {
    LPShareVault private shares;
    uint256 private previousWaterAssets;
    uint256 private previousWaterShares;

    constructor() {
        _deploy();
        shares = lp.shareVault();
        access.grantRole(access.GUARDIAN(), address(controller));
        _settle(0, 0, new uint256[](0));
        shares.setPhase(LPShareVault.Phase.Whitelisted);
        shares.setPhase(LPShareVault.Phase.Public);
        usdc.mint(alice, 10_000_000e6);
        usdc.mint(bob, 10_000_000e6);
        vm.prank(alice);
        usdc.approve(address(shares), type(uint256).max);
        vm.prank(bob);
        usdc.approve(address(shares), type(uint256).max);
        previousWaterAssets = lp.highWaterAssets();
        previousWaterShares = lp.highWaterShares();
    }

    function _resume() private {
        if (access.tradingPaused()) access.resumeTrading();
    }

    function _window() private {
        _resume();
        uint256[] memory ids = new uint256[](0);
        // Nonzero requirements vary with equity and remain fully covered.
        // A zero-exposure checkpoint can still retain an operational capital floor.
        _pauseSettlement(0, custody.customerLiabilityUSDC(), ids, lp.totalLPAssets() / 10);
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

    function _pauseSettlement(int256 pnl, uint256 liability, uint256[] memory ids, uint256 required) private {
        _resume();
        // Account for PnL before choosing a valid post-settlement capital floor.
        uint256 postAssets = pnl >= 0 ? lp.totalLPAssets() - uint256(pnl) : lp.totalLPAssets() + uint256(-pnl);
        if (required > postAssets / 10) required = postAssets / 10;
        SettlementController.EpochSettlement memory r = _report(pnl, liability, ids);
        r.reportedRequiredLPCapitalUSDC = required;
        bytes32 digest = controller.hashSettlement(r);
        controller.settleAndPause(r, ids, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function deposit(uint96 rawAmount, bool useBob) external {
        _window();
        address owner = useBob ? bob : alice;
        uint256 limit = shares.maxDeposit(owner);
        if (limit > usdc.balanceOf(owner)) limit = usdc.balanceOf(owner);
        if (limit > 100_000e6) limit = 100_000e6;
        if (limit == 0) return;
        vm.prank(owner);
        shares.deposit(bound(rawAmount, 1, limit), owner);
    }

    function settlePnL(uint96 rawAmount, bool traderWins) external {
        _resume();
        uint256 amount = bound(rawAmount, 0, 10_000e6);
        uint256 liability = custody.customerLiabilityUSDC();
        uint256[] memory ids = new uint256[](0);
        if (traderWins) {
            if (amount > lp.totalLPAssets() / 4) amount = lp.totalLPAssets() / 4;
            _pauseSettlement(int256(amount), liability + amount, ids, 0);
        } else {
            if (amount != 0) ids = _ids(custody.deposit(amount, alice));
            _pauseSettlement(-int256(amount), liability, ids, 0);
        }
    }

    function request(uint96 rawShares, bool useBob) external {
        address owner = useBob ? bob : alice;
        uint256 balance = shares.balanceOf(owner);
        uint256 minimum = shares.minRedeemShares();
        if (balance < minimum || shares.activeRequest(owner) != 0) return;
        vm.prank(owner);
        shares.requestRedeem(bound(rawShares, minimum, balance), owner, owner);
    }

    function fulfill() external {
        uint256 id = shares.queueHead();
        if (id == shares.nextRequestId()) return;
        (, uint64 readyAt,, uint256 pending,,,,,) = shares.exitRequests(id);
        if (block.timestamp < readyAt) vm.warp(readyAt);
        _window();
        uint256 assets = shares.convertToAssets(pending);
        if (lp.requiredCapitalUSDC() > (lp.totalLPAssets() - assets) / 2) return;
        shares.fulfillRedeem(id);
    }

    function claim(uint96 rawAmount, bool useBob, bool byAssets) external {
        address owner = useBob ? bob : alice;
        uint256 amount = byAssets ? shares.maxWithdraw(owner) : shares.maxRedeem(owner);
        if (amount == 0) return;
        amount = bound(rawAmount, 1, amount);
        vm.prank(owner);
        if (byAssets) shares.withdraw(amount, owner, owner);
        else shares.redeem(amount, owner, owner);
    }

    function fundReserve(uint96 rawAmount) external {
        _window();
        (uint256 amount,) = lp.reserveAllowance(lp.requiredCapitalUSDC());
        if (amount == 0) return;
        _resume();
        uint256 nav = shares.totalAssets();
        _fundReserve(bound(rawAmount, 1, amount));
        assertEq(shares.totalAssets(), nav);
    }

    function checkConservationAndQueue() external {
        assertEq(lp.accountedBalance(), usdc.balanceOf(address(lp)));
        assertEq(lp.accountedBalance(), shares.totalAssets() + lp.reservedExitUSDC() + lp.reserveFeeAccruedUSDC());
        assertEq(
            shares.totalSupply(),
            shares.balanceOf(address(this)) + shares.balanceOf(alice) + shares.balanceOf(bob)
                + shares.balanceOf(address(shares))
        );
        uint256 pending;
        uint256 owed;
        for (uint256 id = 1; id < shares.nextRequestId(); ++id) {
            (
                address requestController,,,
                uint256 amount,
                uint256 assets,
                uint256 claimedShares,
                uint256 paid,
                bool funded,
                address owner
            ) = shares.exitRequests(id);
            if (funded) owed += assets - paid;
            else pending += amount;
            if (claimedShares < amount) {
                assertEq(shares.activeRequest(owner), id);
                assertEq(shares.controllerRequest(requestController), id);
            } else {
                assertTrue(shares.activeRequest(owner) != id);
                assertTrue(shares.controllerRequest(requestController) != id);
            }
        }
        assertEq(pending, shares.balanceOf(address(shares)));
        assertEq(owed, lp.reservedExitUSDC());
        assertEq(lp.reserveDistributedUSDC(), reserve.totalFundedUSDC());
        assertEq(
            usdc.totalSupply(),
            usdc.balanceOf(address(this)) + usdc.balanceOf(alice) + usdc.balanceOf(bob)
                + usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp)) + usdc.balanceOf(address(reserve))
                + usdc.balanceOf(address(shares))
        );
        assertGe(lp.highWaterAssets() * previousWaterShares, previousWaterAssets * lp.highWaterShares());
        previousWaterAssets = lp.highWaterAssets();
        previousWaterShares = lp.highWaterShares();
    }
}

contract LPAccountingInvariantTest is StdInvariant, Test {
    LPAccountingHandler private handler;

    function setUp() public {
        handler = new LPAccountingHandler();
        bytes4[] memory selectors = new bytes4[](6);
        selectors[0] = handler.deposit.selector;
        selectors[1] = handler.settlePnL.selector;
        selectors[2] = handler.request.selector;
        selectors[3] = handler.fulfill.selector;
        selectors[4] = handler.claim.selector;
        selectors[5] = handler.fundReserve.selector;
        targetSelector(FuzzSelector(address(handler), selectors));
        targetContract(address(handler));
    }

    function invariantLPAssetsSharesClaimsAndWatermark() public {
        handler.checkConservationAndQueue();
    }
}
