// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {AccessController} from "../src/AccessController.sol";
import {WithdrawalGateway} from "../src/WithdrawalGateway.sol";
import {CustomerCustodyVault} from "../src/CustomerCustodyVault.sol";
import {Module} from "../src/common/Module.sol";

contract WithdrawalsTest is FUSEFixture {
    function setUp() public {
        _deploy();
        _credit(1000e6);
    }

    function _claim(WithdrawalGateway.WithdrawalAuthorization memory authorization) internal {
        gateway.claim(authorization, _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(authorization)), "");
    }

    function _expectClaimRevert(bytes4 errorSelector, WithdrawalGateway.WithdrawalAuthorization memory authorization)
        internal
    {
        bytes memory signature = _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(authorization));
        vm.expectRevert(errorSelector);
        gateway.claim(authorization, signature, "");
    }

    function testCumulativeClaimsOnlyPayDeltaAndCannotReplay() public {
        WithdrawalGateway.WithdrawalAuthorization memory first =
            _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        _claim(first);
        assertEq(usdc.balanceOf(alice), 100e6);
        WithdrawalGateway.WithdrawalAuthorization memory next = _authorization(alice, alice, 150e6, bytes32(uint256(2)));
        _claim(next);
        assertEq(usdc.balanceOf(alice), 150e6);
        assertEq(gateway.withdrawnCumulative(alice), 150e6);
        assertEq(custody.customerLiabilityUSDC(), 850e6);
        _expectClaimRevert(WithdrawalGateway.InvalidAuthorization.selector, first);
        _expectClaimRevert(WithdrawalGateway.InvalidAuthorization.selector, next);
    }

    function testNewestAuthorizationBeforeOlderNeverDoublePays() public {
        _claim(_authorization(alice, alice, 200e6, bytes32(uint256(2))));
        _expectClaimRevert(
            WithdrawalGateway.InvalidAuthorization.selector, _authorization(alice, alice, 100e6, bytes32(uint256(1)))
        );
        assertEq(usdc.balanceOf(alice), 200e6);
    }

    function testSignerCannotRedirectWithoutAccountConsent() public {
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, bob, 100e6, bytes32(uint256(1)));
        _expectClaimRevert(WithdrawalGateway.RecipientNotAuthorized.selector, authorization);
        assertEq(gateway.withdrawnCumulative(alice), 0);
        bytes32 digest = gateway.hashWithdrawal(authorization);
        gateway.claim(authorization, _sign(WITHDRAWAL_KEY, digest), _sign(ALICE_KEY, digest));
        assertEq(usdc.balanceOf(bob), 100e6);
    }

    function testAccountCanDirectlyAuthorizeAlternateRecipient() public {
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, bob, 100e6, bytes32(uint256(1)));
        bytes memory signature = _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(authorization));
        vm.prank(alice);
        gateway.claim(authorization, signature, "");
        assertEq(usdc.balanceOf(bob), 100e6);
    }

    function testExpiredAndUnfinalizedClaimsRejected() public {
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        authorization.validUntil = uint64(block.timestamp - 1);
        _expectClaimRevert(WithdrawalGateway.InvalidAuthorization.selector, authorization);
        authorization.validUntil = uint64(block.timestamp + 1 hours);
        authorization.stateVersion = controller.latestEpoch() + 1;
        _expectClaimRevert(WithdrawalGateway.InvalidAuthorization.selector, authorization);
    }

    function testInsufficientFundedLiabilityRollsBackReplayState() public {
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, alice, 1001e6, bytes32(uint256(1)));
        _expectClaimRevert(CustomerCustodyVault.InsufficientBacking.selector, authorization);
        assertEq(gateway.withdrawnCumulative(alice), 0);
        assertFalse(gateway.usedAuthorizations(authorization.authorizationId));
    }

    function testPauseStopsDepositsButHonorsFundedClaimsAndRefunds() public {
        uint256 id = custody.deposit(50e6, alice);
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        authorization.validUntil = uint64(block.timestamp + 2 days);
        access.pauseTrading();
        vm.expectRevert(Module.TradingPaused.selector);
        custody.deposit(1, alice);
        _claim(authorization);
        vm.warp(block.timestamp + 1 days);
        custody.refundUncreditedDeposit(id);
        assertEq(usdc.balanceOf(alice), 100e6);
    }

    function testRotatedSigningDomainRejectsOldAuthorization() public {
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        bytes memory signature = _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(authorization));
        access.setSigner(access.WITHDRAWAL_SIGNER(), vm.addr(0x555));
        vm.expectRevert(AccessController.InvalidSignature.selector);
        gateway.claim(authorization, signature, "");
    }

    function testCrossChainAndCrossGatewayReplayRejected() public {
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        bytes memory signature = _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(authorization));
        vm.chainId(block.chainid + 1);
        vm.expectRevert(AccessController.InvalidSignature.selector);
        gateway.claim(authorization, signature, "");
    }

    function testUSDCReentrancyCannotDuplicateWithdrawal() public {
        WithdrawalGateway.WithdrawalAuthorization memory authorization =
            _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        bytes memory signature = _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(authorization));
        usdc.setCallback(address(gateway), abi.encodeCall(gateway.claim, (authorization, signature, bytes(""))));
        gateway.claim(authorization, signature, "");
        assertFalse(usdc.callbackSucceeded());
        assertEq(usdc.balanceOf(alice), 100e6);
    }

    function testFuzzCumulativeWithdrawal(uint96 firstRaw, uint96 nextRaw) public {
        uint256 first = bound(firstRaw, 1, 500e6);
        uint256 next = bound(nextRaw, first + 1, 1000e6);
        _claim(_authorization(alice, alice, first, bytes32(uint256(1))));
        _claim(_authorization(alice, alice, next, bytes32(uint256(2))));
        assertEq(usdc.balanceOf(alice), next);
        assertEq(custody.customerLiabilityUSDC(), 1000e6 - next);
    }
}
