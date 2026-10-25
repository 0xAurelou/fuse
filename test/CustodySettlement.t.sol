// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {AccessController} from "../src/AccessController.sol";
import {CustomerCustodyVault} from "../src/CustomerCustodyVault.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {LPVault} from "../src/LPVault.sol";
import {Module} from "../src/common/Module.sol";
import {ExactTransfer} from "../src/common/ExactTransfer.sol";

contract CustodySettlementTest is FUSEFixture {
    function setUp() public {
        _deploy();
    }

    function _expectSettleRevert(bytes4 errorSelector, int256 pnl, uint256 liability, uint256[] memory ids) internal {
        _expectSubmitRevert(errorSelector, _report(pnl, liability, ids), ids);
    }

    function _expectSubmitRevert(
        bytes4 errorSelector,
        SettlementController.EpochSettlement memory report,
        uint256[] memory ids
    ) internal {
        bytes32 digest = controller.hashSettlement(report);
        bytes memory settlementSig = _sign(SETTLEMENT_KEY, digest);
        bytes memory riskSig = _sign(RISK_KEY, digest);
        vm.expectRevert(errorSelector);
        controller.settle(report, ids, settlementSig, riskSig);
    }

    function testDepositReceiptAndPermissionlessRefundToPayer() public {
        uint256 balance = usdc.balanceOf(address(this));
        uint256 id = custody.deposit(100e6, alice);
        (address payer, address beneficiary, uint256 amount,,, CustomerCustodyVault.DepositStatus status) =
            custody.deposits(id);
        assertEq(payer, address(this));
        assertEq(beneficiary, alice);
        assertEq(amount, 100e6);
        assertEq(uint256(status), uint256(CustomerCustodyVault.DepositStatus.Pending));
        vm.expectRevert(CustomerCustodyVault.InvalidDeposit.selector);
        custody.refundUncreditedDeposit(id);
        vm.warp(block.timestamp + 1 days);
        vm.prank(bob);
        custody.refundUncreditedDeposit(id);
        assertEq(usdc.balanceOf(address(this)), balance);
        assertEq(usdc.balanceOf(bob), 0);
        assertEq(custody.uncreditedBalance(), 0);
        vm.expectRevert(CustomerCustodyVault.InvalidDeposit.selector);
        custody.refundUncreditedDeposit(id);
        _expectSettleRevert(CustomerCustodyVault.InvalidDeposit.selector, 0, 0, _ids(id));
    }

    function testCreditedDepositCannotBeRefunded() public {
        _credit(100e6);
        vm.warp(block.timestamp + 1 days);
        vm.expectRevert(CustomerCustodyVault.InvalidDeposit.selector);
        custody.refundUncreditedDeposit(1);
        assertEq(custody.customerLiabilityUSDC(), 100e6);
    }

    function testUncreditedFundsCannotPayTraderLosses() public {
        custody.deposit(100e6, alice);
        _expectSettleRevert(CustomerCustodyVault.InsufficientBacking.selector, -100e6, 0, new uint256[](0));
        assertEq(controller.latestEpoch(), 0);
        assertEq(custody.uncreditedBalance(), 100e6);
    }

    function testUncreditedDepositsCannotBackNewLiabilities() public {
        custody.deposit(100e6, alice);
        _expectSettleRevert(CustomerCustodyVault.InsufficientBacking.selector, 0, 1, new uint256[](0));
    }

    function testNetSettlementsConserveUSDCAndCommitOrderedRoots() public {
        _credit(100e6);
        uint256 total = usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp));
        _settle(-30e6, 70e6, new uint256[](0));
        assertEq(usdc.balanceOf(address(custody)), 70e6);
        assertEq(lp.realizedProfitHWMUSDC(), 30e6);
        bytes32 root = controller.currentRoot();
        _settle(20e6, 90e6, new uint256[](0));
        assertEq(usdc.balanceOf(address(custody)), 90e6);
        assertEq(total, usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp)));
        assertEq(lp.cumulativeRealizedProfitUSDC(), 10e6);
        assertEq(lp.realizedProfitHWMUSDC(), 30e6);
        assertEq(controller.latestEpoch(), 3);
        assertTrue(controller.currentRoot() != root);
        assertTrue(controller.checkpointHash(3) != bytes32(0));
    }

    function testSettlementCannotReplay() public {
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory report = _report(0, 0, ids);
        _submit(report, ids);
        _expectSubmitRevert(SettlementController.InvalidCheckpoint.selector, report, ids);
    }

    function testInsufficientLPFundingRollsBackDepositAcknowledgment() public {
        uint256 id = custody.deposit(100e6, alice);
        _expectSettleRevert(LPVault.InvalidSettlement.selector, int256(lp.accountedBalance() + 1), 100e6, _ids(id));
        (,,,,, CustomerCustodyVault.DepositStatus status) = custody.deposits(id);
        assertEq(uint256(status), uint256(CustomerCustodyVault.DepositStatus.Pending));
        assertEq(custody.uncreditedBalance(), 100e6);
        assertEq(controller.latestEpoch(), 0);
    }

    function testUnderfundedLiabilityAndCapitalRevertAtomically() public {
        uint256 id = custody.deposit(100e6, alice);
        _expectSettleRevert(CustomerCustodyVault.InsufficientBacking.selector, -50e6, 51e6, _ids(id));
        assertEq(custody.uncreditedBalance(), 100e6);
        assertEq(lp.cumulativeRealizedProfitUSDC(), 0);
        SettlementController.EpochSettlement memory report = _report(10e6, 110e6, _ids(id));
        report.reportedRequiredLPCapitalUSDC = usdc.balanceOf(address(lp));
        _expectSubmitRevert(LPVault.InsufficientCapital.selector, report, _ids(id));
        assertEq(usdc.balanceOf(address(custody)), 100e6);
        assertEq(custody.uncreditedBalance(), 100e6);
    }

    function testDistinctRiskSignatureRequired() public {
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory report = _report(0, 0, ids);
        bytes memory signature = _sign(SETTLEMENT_KEY, controller.hashSettlement(report));
        vm.expectRevert(AccessController.InvalidSignature.selector);
        controller.settle(report, ids, signature, signature);
        bytes32 riskRole = access.RISK_SIGNER();
        address settlementSigner = vm.addr(SETTLEMENT_KEY);
        vm.expectRevert(AccessController.InvalidAuthority.selector);
        access.setSigner(riskRole, settlementSigner);
    }

    function testRotationInvalidatesPreSignedCheckpoint() public {
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory report = _report(0, 0, ids);
        bytes32 digest = controller.hashSettlement(report);
        bytes memory settlementSig = _sign(SETTLEMENT_KEY, digest);
        bytes memory riskSig = _sign(RISK_KEY, digest);
        access.setSigner(access.WITHDRAWAL_SIGNER(), vm.addr(0x999));
        vm.expectRevert(AccessController.InvalidSignature.selector);
        controller.settle(report, ids, settlementSig, riskSig);
    }

    function testCheckpointRejectsExpiredUnorderedAndMismatchedBatches() public {
        uint256[] memory ids = new uint256[](0);
        SettlementController.EpochSettlement memory report = _report(0, 0, ids);
        report.deadline = block.timestamp - 1;
        _expectSubmitRevert(SettlementController.InvalidCheckpoint.selector, report, ids);
        report = _report(0, 0, ids);
        report.fromSequence = 2;
        _expectSubmitRevert(SettlementController.InvalidCheckpoint.selector, report, ids);
        report = _report(0, 0, ids);
        _expectSubmitRevert(SettlementController.InvalidCheckpoint.selector, report, _ids(1));
        report = _report(0, 0, ids);
        report.priorRoot = bytes32(uint256(1));
        _expectSubmitRevert(SettlementController.InvalidCheckpoint.selector, report, ids);
    }

    function testRejectsFalseHWMAndUnderreportedCapital() public {
        SettlementController.EpochSettlement memory report = _report(0, 0, new uint256[](0));
        report.realizedProfitHWMUSDC = 1;
        _expectSubmitRevert(LPVault.InvalidSettlement.selector, report, new uint256[](0));
        report = _report(0, 0, new uint256[](0));
        report.reportedMaxOpenExposureUSDC = 1;
        _expectSubmitRevert(SettlementController.InvalidCheckpoint.selector, report, new uint256[](0));
    }

    function testDuplicateDepositBatchReverts() public {
        uint256 id = custody.deposit(100e6, alice);
        uint256[] memory ids = new uint256[](2);
        ids[0] = id;
        ids[1] = id;
        _expectSettleRevert(CustomerCustodyVault.InvalidDeposit.selector, 0, 100e6, ids);
        assertEq(custody.uncreditedBalance(), 100e6);
    }

    function testTaxedUSDCRejectedOnDepositLPAndRefund() public {
        uint256 id = custody.deposit(100e6, alice);
        usdc.setTaxed(true);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        custody.deposit(100e6, alice);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        lp.depositLP(100e6);
        vm.warp(block.timestamp + 1 days);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        custody.refundUncreditedDeposit(id);
        assertEq(custody.uncreditedBalance(), 100e6);
        assertEq(custody.nextDepositId(), 2);
    }

    function testNoAdministratorSweepOrPublicLPExit() public {
        vm.expectRevert(Module.Unauthorized.selector);
        custody.payUser(bob, 1, bytes32(uint256(1)));
        vm.expectRevert(Module.Unauthorized.selector);
        custody.transferRealizedLossToLP(1, 1);
        vm.expectRevert(LPVault.PublicLPExitsDisabled.selector);
        lp.executeLPExit();
        vm.expectRevert(LPVault.PublicLPExitsDisabled.selector);
        lp.requestLPExit();
        vm.expectRevert(Module.InvalidConfiguration.selector);
        custody.configure(address(controller), address(gateway), address(lp));
    }

    function testFuzzSettlementConservation(uint96 customerFunds, uint96 rawPnl, bool traderWins) public {
        uint256 funds = bound(customerFunds, 1, 100_000e6);
        uint256 pnl = bound(rawPnl, 0, traderWins ? lp.accountedBalance() : funds);
        _credit(funds);
        uint256 total = usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp));
        int256 net = traderWins ? int256(pnl) : -int256(pnl);
        _settle(net, traderWins ? funds + pnl : funds - pnl, new uint256[](0));
        assertEq(usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp)), total);
        assertGe(usdc.balanceOf(address(custody)), custody.uncreditedBalance() + custody.customerLiabilityUSDC());
    }
}
