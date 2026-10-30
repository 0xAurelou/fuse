// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "./helpers/FUSEFixture.sol";
import {AccessController} from "../src/AccessController.sol";
import {Module} from "../src/common/Module.sol";
import {ExactTransfer} from "../src/common/ExactTransfer.sol";
import {DailyLPVault, IDailyCustodyIdentity, IDailyBacking} from "../src/DailyLPVault.sol";
import {DailyBetCustody} from "../src/DailyBetCustody.sol";
import {FUSEToken} from "../src/FUSEToken.sol";
import {RedemptionReserve} from "../src/RedemptionReserve.sol";
import {DailyAccountingVectors} from "./fixtures/DailyAccountingVectors.sol";

contract DailyLPTest is Test {
    AccessController internal access;
    MockUSDC internal usdc;
    DailyLPVault internal vault;
    DailyBetCustody internal custody;
    RedemptionReserve internal reserve;
    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);
    address internal player = address(0xCAFE);
    address internal operator = address(0xFEE);
    uint256 internal nonce;
    uint256 internal depositNonce;
    uint256 internal constant SETTLEMENT_KEY = 0x111;
    uint256 internal constant RISK_KEY = 0x222;

    function setUp() public {
        vm.warp(1_793_318_400); // midnight UTC
        access = new AccessController(address(this));
        access.setSigner(access.SETTLEMENT_SIGNER(), vm.addr(SETTLEMENT_KEY));
        access.setSigner(access.RISK_SIGNER(), vm.addr(RISK_KEY));
        access.grantRole(access.GUARDIAN(), address(this));
        usdc = new MockUSDC();
        _deploy(0, 0, 0);
    }

    function _deploy(uint256 admission, uint256 distribution, uint256 backing) internal {
        DailyLPVault.Limits memory caps = DailyLPVault.Limits({
            perBet: 1_000_000e6,
            perMarket: [uint256(2_000_000e6), 2_000_000e6, 2_000_000e6],
            total: 3_000_000e6,
            admissionBuffer: admission,
            distributionBuffer: distribution,
            backingBuffer: backing
        });
        vault = new DailyLPVault(access, usdc, operator, caps);
        custody = new DailyBetCustody(access, usdc, vault, 2_000_000e6, 1024);
        FUSEToken token = new FUSEToken(access, 1 days);
        reserve = new RedemptionReserve(access, usdc, token, address(vault));
        vault.configure(IDailyCustodyIdentity(address(custody)), IDailyBacking(address(reserve)));
        access.pauseTrading();
        _fundCustomer(player, 10_000_000e6);
    }

    function _fundCustomer(address account, uint256 amount) internal {
        usdc.mint(account, amount);
        vm.startPrank(account);
        usdc.approve(address(custody), type(uint256).max);
        custody.deposit(amount);
        vm.stopPrank();
    }

    function _deposit(address owner, uint256 amount) internal returns (uint256 id) {
        usdc.mint(owner, amount);
        DailyLPVault.DepositAuthorization memory a = DailyLPVault.DepositAuthorization(
            owner, amount, keccak256(abi.encode("deposit", ++depositNonce)), uint64(block.timestamp + 100)
        );
        bytes32 digest = vault.hashDeposit(a);
        bytes memory s = _sign(SETTLEMENT_KEY, digest);
        bytes memory r = _sign(RISK_KEY, digest);
        vm.startPrank(owner);
        usdc.approve(address(vault), type(uint256).max);
        id = vault.deposit(a, s, r);
        vm.stopPrank();
    }

    function _sign(uint256 key, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    function _quote(uint8 asset, uint256 stake, uint256 multiplier) internal returns (DailyBetCustody.Quote memory q) {
        q = DailyBetCustody.Quote({
            id: bytes32(++nonce),
            account: player,
            asset: asset,
            stake: stake,
            multiplier: multiplier,
            lower: 99e8,
            referencePrice: 100e8,
            upper: 101e8,
            quotedAt: uint64(block.timestamp),
            validUntil: uint64(block.timestamp + 5),
            pricingHash: keccak256("test-pricing")
        });
    }

    function _acceptQuote(DailyBetCustody.Quote memory q) internal {
        bytes32 digest = custody.hashQuote(q);
        bytes memory settlement = _sign(SETTLEMENT_KEY, digest);
        bytes memory risk = _sign(RISK_KEY, digest);
        vm.prank(player);
        custody.accept(q, settlement, risk);
    }

    function _accept(uint8 asset, uint256 stake, uint256 multiplier) internal returns (bytes32 id) {
        DailyBetCustody.Quote memory q = _quote(asset, stake, multiplier);
        _acceptQuote(q);
        return q.id;
    }

    function _outcome(bytes32 id, uint8 outcome, uint64 canonical)
        internal
        view
        returns (DailyBetCustody.Outcome memory o)
    {
        o = DailyBetCustody.Outcome(
            id, outcome, canonical * 1000, keccak256("test-oracle-evidence"), uint64(block.timestamp + 100)
        );
    }

    function _resolve(DailyBetCustody.Outcome memory o) internal {
        bytes32 digest = custody.hashOutcome(o);
        custody.resolve(o, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _trade(uint256 stake, uint8 outcome) internal {
        bytes32 id = _accept(0, stake, 2);
        uint64 canonical = uint64(block.timestamp + (outcome == 3 ? 1 : 30));
        vm.warp(block.timestamp + 30);
        _resolve(_outcome(id, outcome, canonical));
    }

    function _closeReport(uint256 need) internal view returns (DailyBetCustody.DailyClose memory c) {
        c = DailyBetCustody.DailyClose(
            vault.currentDay(),
            uint64(vault.cutoff() * 1000),
            vault.betSequence(),
            0,
            0,
            need,
            keccak256("test-journal-watermark"),
            uint64(block.timestamp + 100)
        );
    }

    function _submitClose(DailyBetCustody.DailyClose memory c) internal {
        bytes32 digest = custody.hashClose(c);
        custody.closeDay(c, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _close(uint256 need) internal returns (uint64 day) {
        day = vault.currentDay();
        vm.warp(vault.cutoff());
        _submitClose(_closeReport(need));
    }

    function _lot(uint256 id) internal view returns (DailyLPVault.Lot memory l) {
        (l.owner, l.equity, l.reserved, l.pnl, l.mark, l.exitRequested, l.archived) = vault.lots(id);
    }

    function _invariants() internal view {
        uint256 equity;
        uint256 exposure;
        uint256[] memory ids = vault.activeLots();
        for (uint256 i; i < ids.length; ++i) {
            DailyLPVault.Lot memory l = _lot(ids[i]);
            assertFalse(l.archived);
            assertGe(l.equity, l.reserved);
            equity += l.equity;
            exposure += l.reserved;
        }
        assertEq(equity, vault.totalEquity());
        assertEq(exposure, vault.openExposure());
        assertEq(vault.availableCash(), equity);
        assertGe(usdc.balanceOf(address(vault)), vault.accountedCash());
        assertGe(equity, exposure);
        assertEq(
            int256(equity + vault.totalExited() + vault.totalFees() + vault.totalBacking()),
            int256(vault.totalContributed()) + vault.totalRealized()
        );
        assertGe(usdc.balanceOf(address(custody)), custody.totalAvailable() + custody.totalLocked());
    }

    function testIdleFullWithdrawalNeedsNoRequestTimerOrAdmissionHeadroom() public {
        _deploy(100e6, 200e6, 300e6);
        uint256 id = _deposit(alice, 1000e6);
        vm.warp(vault.cutoff() + 3 days);
        assertEq(vault.maxWithdrawal(id), 1000e6);
        vm.prank(alice);
        vault.withdraw(id, 1000e6);
        assertTrue(_lot(id).archived);
        assertEq(vault.accountedCash(), 0);
        _invariants();
    }

    function testOriginalUnderwritersBearTheirOwnWinAfterPartialExit() public {
        uint256 a = _deposit(alice, 1000e6);
        uint256 b = _deposit(bob, 1000e6);
        access.resumeTrading();
        bytes32 id = _accept(0, 200e6, 2);
        assertEq(vault.maxWithdrawal(a), 900e6);
        vm.prank(alice);
        vault.withdraw(a, 900e6);
        access.pauseTrading();
        vm.warp(block.timestamp + 30);
        _resolve(_outcome(id, 2, uint64(block.timestamp)));
        assertEq(_lot(a).equity, 0);
        assertEq(_lot(b).equity, 900e6);
        assertEq(_lot(a).pnl, -100e6);
        assertEq(_lot(b).pnl, -100e6);
        assertEq(custody.available(player), 10_000_200e6);
        vm.prank(player);
        custody.withdraw(10_000_200e6);
        vault.archiveEmptyLot(a);
        assertTrue(_lot(a).archived);
        _invariants();
    }

    function testLateOutcomeAndClosePreserveDayWhilePrincipalExits() public {
        uint256 lot = _deposit(alice, 1000e6);
        access.resumeTrading();
        bytes32 id = _accept(0, 100e6, 2);
        uint64 hit = uint64(block.timestamp + 1);
        uint64 day = vault.currentDay();
        vm.warp(vault.cutoff() + 1 hours);
        vm.prank(alice);
        vault.requestExit(lot, true);
        vm.prank(alice);
        vault.withdraw(lot, 900e6);
        vm.expectRevert(DailyLPVault.CloseRequired.selector);
        this.acceptForPlayer();
        _resolve(_outcome(id, 3, hit));
        assertEq(vault.maxWithdrawal(lot), 100e6);
        _submitClose(_closeReport(0));
        assertEq(vault.operatorDue(), 5e6);
        assertEq(vault.maxWithdrawal(lot), 195e6);
        vm.prank(alice);
        vault.withdraw(lot, 195e6);
        vault.payFee(day);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        vault.payFee(day);
        assertEq(usdc.balanceOf(operator), 5e6);
        assertEq(vault.accountedCash(), 0);
        _invariants();
    }

    function acceptForPlayer() external {
        _accept(0, 1, 2);
    }

    function testBothTransactionOrdersRecheckAtomicAdmissionAndWithdrawal() public {
        _deploy(100e6, 100e6, 100e6);
        uint256 lot = _deposit(alice, 1000e6);
        access.resumeTrading();
        uint256 shown = vault.maxWithdrawal(lot);
        bytes32 id = _accept(0, 100e6, 2);
        vm.prank(alice);
        vm.expectRevert(DailyLPVault.InsufficientCapital.selector);
        vault.withdraw(lot, shown);
        vm.prank(alice);
        vault.withdraw(lot, 900e6);
        vm.expectRevert(DailyLPVault.InsufficientCapital.selector);
        this.acceptForPlayer();
        vm.warp(block.timestamp + 30);
        _resolve(_outcome(id, 4, uint64(block.timestamp)));
        vm.prank(alice);
        vault.withdraw(lot, 100e6);
        assertEq(vault.totalEquity(), 0);
        _invariants();
    }

    function testLossCarryforwardNeverResetsAtCloseOrWithdrawal() public {
        uint256 lot = _deposit(alice, 10_000e6);
        access.resumeTrading();
        int256[6] memory pnls = [int256(-1000e6), 800e6, 500e6, -300e6, 300e6, 100e6];
        uint256[6] memory fees = [uint256(0), 0, 15e6, 0, 0, 5e6];
        for (uint256 i; i < pnls.length; ++i) {
            _trade(uint256(pnls[i] < 0 ? -pnls[i] : pnls[i]), pnls[i] < 0 ? 2 : 3);
            uint64 day = _close(0);
            (,, uint256 fee,,,) = vault.closes(day);
            assertEq(fee, fees[i]);
            _invariants();
        }
        assertEq(_lot(lot).mark, 400e6);
        assertEq(vault.totalFees(), 20e6);
    }

    function testNewcomerHasOwnProfitAndCannotInheritOldLosses() public {
        uint256 old = _deposit(alice, 2000e6);
        access.resumeTrading();
        _trade(1000e6, 2);
        _close(0);
        access.pauseTrading();
        vm.warp(block.timestamp + 10);
        uint256 fresh = _deposit(bob, 2000e6);
        access.resumeTrading();
        _trade(1500e6, 3);
        _close(0);
        assertEq(_lot(old).pnl, -500e6);
        assertEq(_lot(old).equity, 1500e6);
        assertEq(_lot(fresh).pnl, 1000e6);
        assertEq(_lot(fresh).equity, 2950e6);
        assertEq(vault.totalFees(), 50e6);
        _invariants();
    }

    function testBoundaryExpiryRemainsOldOwnersRiskButIsNewDayPnL() public {
        _deposit(alice, 1000e6);
        access.resumeTrading();
        uint256 end = vault.cutoff();
        vm.warp(end - 30);
        bytes32 id = _accept(1, 100e6, 2);
        vm.warp(end);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        this.resolveFromTest(id, 2, uint64(end));
        _submitClose(_closeReport(0));
        assertEq(vault.openExposure(), 100e6);
        _resolve(_outcome(id, 2, uint64(end)));
        assertEq(vault.openExposure(), 0);
        _close(0);
        assertEq(vault.totalFees(), 0);
        _invariants();
    }

    function resolveFromTest(bytes32 id, uint8 outcome, uint64 canonical) external {
        _resolve(_outcome(id, outcome, canonical));
    }

    function testMissingPreboundaryOutcomeBlocksCloseButNotFreePrincipal() public {
        uint256 lot = _deposit(alice, 1000e6);
        access.resumeTrading();
        _accept(0, 100e6, 2);
        vm.warp(vault.cutoff());
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        this.submitCloseFromTest(0);
        vm.prank(alice);
        vault.withdraw(lot, 900e6);
        assertEq(vault.accountedCash(), 100e6);
        _invariants();
    }

    function submitCloseFromTest(uint256 need) external {
        _submitClose(_closeReport(need));
    }

    function testExitRequestStopsNewUnderwritingAndCancellationPreservesMark() public {
        uint256 lot = _deposit(alice, 1000e6);
        vm.prank(alice);
        vault.requestExit(lot, true);
        access.resumeTrading();
        vm.expectRevert(DailyLPVault.InsufficientCapital.selector);
        this.acceptForPlayer();
        vm.prank(alice);
        vault.requestExit(lot, false);
        _trade(100e6, 3);
        _close(0);
        assertEq(_lot(lot).mark, 100e6);
        assertEq(_lot(lot).pnl, 100e6);
        _invariants();
    }

    function testFeeBeforeBackingReservationsSurviveWinnerAndFullLPExit() public {
        uint256 lot = _deposit(alice, 1100);
        access.resumeTrading();
        _trade(1000, 3);
        uint64 day = _close(100);
        (,, uint256 fee, uint256 backing,,) = vault.closes(day);
        assertEq(fee, 50);
        assertEq(backing, 223);
        _trade(100, 2);
        access.pauseTrading();
        uint256 free = vault.maxWithdrawal(lot);
        vm.prank(alice);
        vault.withdraw(lot, free);
        assertEq(vault.accountedCash(), fee + backing);
        vault.payBacking(day);
        vault.payFee(day);
        assertEq(reserve.totalFundedUSDC(), 223);
        assertEq(usdc.allowance(address(vault), address(reserve)), 0);
        assertEq(vault.accountedCash(), 0);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        vault.payBacking(day);
        _invariants();
    }

    function testProtectedProfitCannotBeForgivenOrWithdrawnAcrossCutoff() public {
        uint256 lot = _deposit(alice, 1000);
        access.resumeTrading();
        _trade(1000, 3);
        vm.warp(vault.cutoff() - 1);
        bytes32 id = _accept(0, 2000, 2);
        _close(0);
        assertEq(_lot(lot).mark, 0);
        assertEq(vault.totalFees(), 0);
        vm.warp(block.timestamp + 30);
        _resolve(_outcome(id, 4, uint64(block.timestamp)));
        assertEq(vault.maxWithdrawal(lot), 1000);
        _close(0);
        assertEq(vault.totalFees(), 50);
        _close(0);
        assertEq(vault.totalFees(), 50);
        _invariants();
    }

    function testDailyAggregateFeeRoundingAndStableLotTies() public {
        for (uint256 i; i < 20; ++i) {
            _deposit(address(uint160(100 + i)), 100);
        }
        access.resumeTrading();
        _trade(20, 3);
        _close(0);
        assertEq(vault.totalFees(), 1);
        assertEq(_lot(1).equity, 100);
        assertEq(_lot(2).equity, 101);
        _invariants();
    }

    function testDonationsCannotManufactureProfitOrShares() public {
        uint256 lot = _deposit(alice, 1000e6);
        usdc.mint(address(vault), 1000e6);
        usdc.mint(address(custody), 1000e6);
        _close(0);
        assertEq(vault.maxWithdrawal(lot), 1000e6);
        assertEq(vault.totalFees(), 0);
        vm.prank(alice);
        vault.withdraw(lot, 1000e6);
        assertEq(usdc.balanceOf(address(vault)), 1000e6);
        _invariants();
    }

    function testTaxedLossTransferRollsBackTicketAndAllCapitalState() public {
        uint256 lot = _deposit(alice, 1000e6);
        access.resumeTrading();
        bytes32 id = _accept(0, 100e6, 2);
        uint64 hit = uint64(block.timestamp + 1);
        vm.warp(block.timestamp + 30);
        uint256 seq = vault.sequence();
        usdc.setTaxed(true);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        this.resolveFromTest(id, 3, hit);
        (,,,, bool resolved,) = custody.tickets(id);
        assertFalse(resolved);
        assertEq(_lot(lot).reserved, 100e6);
        assertEq(vault.sequence(), seq);
        assertEq(custody.totalLocked(), 100e6);
        usdc.setTaxed(false);
        _resolve(_outcome(id, 3, hit));
        _invariants();
    }

    function testTaxedWinnerTransferRollsBackUntilSafeRetry() public {
        _deposit(alice, 1000e6);
        access.resumeTrading();
        bytes32 id = _accept(0, 100e6, 2);
        vm.warp(block.timestamp + 30);
        usdc.setTaxed(true);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        this.resolveFromTest(id, 2, uint64(block.timestamp));
        assertEq(vault.openExposure(), 100e6);
        usdc.setTaxed(false);
        _resolve(_outcome(id, 2, uint64(block.timestamp)));
        assertEq(vault.openExposure(), 0);
        _invariants();
    }

    function testCloseAuthorizationSurvivesSafeLPWithdrawalAndRejectsReplay() public {
        uint256 lot = _deposit(alice, 1000e6);
        access.resumeTrading();
        _trade(100e6, 3);
        vm.warp(vault.cutoff());
        DailyBetCustody.DailyClose memory c = _closeReport(0);
        bytes32 digest = custody.hashClose(c);
        bytes memory s = _sign(SETTLEMENT_KEY, digest);
        bytes memory r = _sign(RISK_KEY, digest);
        vm.prank(alice);
        vault.withdraw(lot, 1000e6);
        custody.closeDay(c, s, r);
        assertEq(vault.maxWithdrawal(lot), 95e6);
        vm.expectRevert(DailyBetCustody.InvalidAuthorization.selector);
        custody.closeDay(c, s, r);
        _invariants();
    }

    function testQuoteTamperingMissingRoleAndSignerRotationCannotSpendCustomerCash() public {
        _deposit(alice, 1000e6);
        access.resumeTrading();
        DailyBetCustody.Quote memory q = _quote(0, 100e6, 2);
        bytes32 digest = custody.hashQuote(q);
        bytes memory s = _sign(SETTLEMENT_KEY, digest);
        bytes memory r = _sign(RISK_KEY, digest);
        q.stake += 1;
        vm.prank(player);
        vm.expectRevert(AccessController.InvalidSignature.selector);
        custody.accept(q, s, r);
        q.stake -= 1;
        vm.prank(player);
        vm.expectRevert(AccessController.InvalidSignature.selector);
        custody.accept(q, s, s);
        access.setSigner(access.RISK_SIGNER(), vm.addr(0x999));
        vm.prank(player);
        vm.expectRevert(AccessController.InvalidSignature.selector);
        custody.accept(q, s, r);
        assertEq(custody.totalLocked(), 0);
        _invariants();
    }

    function testUnauthorizedDirectCallsAndCrossAccountWithdrawalsFail() public {
        uint256 lot = _deposit(alice, 1000e6);
        vm.expectRevert(Module.Unauthorized.selector);
        vault.accept(bytes32(uint256(1)), 0, 1, 2);
        uint64 end = uint64(vault.cutoff());
        vm.expectRevert(Module.Unauthorized.selector);
        vault.closeDay(end, 0, 0, 0);
        vm.prank(bob);
        vm.expectRevert(Module.Unauthorized.selector);
        vault.withdraw(lot, 1);
        vm.prank(bob);
        vm.expectRevert(DailyBetCustody.InsufficientBalance.selector);
        custody.withdraw(1);
        _invariants();
    }

    function testFuzzCashConservationAcrossWithdrawalsOutcomesAndDailyFees(uint96 seed, uint8 rounds) public {
        _deposit(alice, 1_000_000e6);
        _deposit(bob, 1_000_000e6);
        access.resumeTrading();
        rounds = uint8(bound(rounds, 1, 30));
        uint256 entropy = seed;
        for (uint256 i; i < rounds; ++i) {
            entropy = uint256(keccak256(abi.encode(entropy, i)));
            uint256 stake = 1 + entropy % 1000e6;
            uint8 outcome = uint8(2 + entropy / 1000e6 % 3);
            _trade(stake, outcome);
            if (entropy % 2 == 0) {
                uint256 lot = 1 + entropy % 2;
                uint256 free = vault.maxWithdrawal(lot);
                if (free > 1) {
                    vm.prank(_lot(lot).owner);
                    vault.withdraw(lot, 1 + entropy % (free / 100 + 1));
                }
            }
            if (i % 5 == 4) _close(entropy % 1000e6);
            _invariants();
        }
        _close(0);
        _invariants();
    }

    function testPythonLedgerDifferentialTransitionsWithOriginalOwnershipAndLateClose() public {
        uint256 genesisDay = DailyAccountingVectors.START / 1 days;
        for (uint256 i; i < DailyAccountingVectors.COUNT; ++i) {
            DailyAccountingVectors.Action memory a = DailyAccountingVectors.action(i);
            vm.warp(a.at);
            if (a.kind == 0) {
                access.pauseTrading();
                address owner = a.key == 1 ? alice : a.key == 2 ? bob : address(0xDAD);
                assertEq(_deposit(owner, a.amount), a.key);
                access.resumeTrading();
            } else if (a.kind == 1) {
                assertEq(_accept(a.asset, a.amount, a.multiplier), bytes32(a.key));
            } else if (a.kind <= 4) {
                _resolve(_outcome(bytes32(a.key), a.kind, a.canonical));
            } else if (a.kind == 5) {
                vm.prank(_lot(a.key).owner);
                vault.withdraw(a.key, a.amount);
            } else if (a.kind == 6) {
                _submitClose(_closeReport(a.amount));
            } else if (a.kind == 7) {
                uint64 day = uint64(genesisDay + a.key);
                (,, uint256 fee, uint256 backing,,) = vault.closes(day);
                if (fee != 0) vault.payFee(day);
                if (backing != 0) vault.payBacking(day);
            } else if (a.kind == 8) {
                _resolve(_outcome(bytes32(a.key), 4, a.canonical));
            } else if (a.kind == 9) {
                custody.completeVoid(bytes32(a.key));
            }
            int256[24] memory expected = DailyAccountingVectors.expected(i);
            assertEq(vault.accountedCash(), uint256(expected[0]), "cash");
            assertEq(vault.openExposure(), uint256(expected[1]), "exposure");
            assertEq(vault.operatorDue(), uint256(expected[2]), "fee due");
            assertEq(vault.backingDue(), uint256(expected[3]), "backing due");
            assertEq(vault.totalFees(), uint256(expected[4]), "fees");
            assertEq(vault.totalBacking(), uint256(expected[5]), "backing");
            assertEq(vault.totalRealized(), expected[6], "realized");
            assertEq(vault.currentDay() - genesisDay, uint256(expected[7]), "day");
            assertEq(custody.available(player), uint256(expected[8]), "customer available");
            for (uint256 lotId = 1; lotId <= 3; ++lotId) {
                DailyLPVault.Lot memory l = _lot(lotId);
                uint256 start = 9 + (lotId - 1) * 5;
                assertEq(l.equity, uint256(expected[start]), "lot equity");
                assertEq(l.reserved, uint256(expected[start + 1]), "lot reserved");
                assertEq(l.pnl, expected[start + 2], "lot pnl");
                assertEq(l.mark, uint256(expected[start + 3]), "lot mark");
                assertEq(vault.maxWithdrawal(lotId), uint256(expected[start + 4]), "lot free");
            }
            _invariants();
        }
    }

    function testEveryAdvertisedMarketPayoutHasFundedAtomicSettlement() public {
        _deposit(alice, 1_000_000e6);
        access.resumeTrading();
        uint256[9] memory multipliers = [uint256(2), 5, 10, 25, 50, 100, 250, 1000, 10000];
        for (uint8 asset; asset < 3; ++asset) {
            for (uint256 i; i < multipliers.length; ++i) {
                bytes32 id = _accept(asset, 1e6, multipliers[i]);
                vm.warp(block.timestamp + 30);
                _resolve(_outcome(id, 2, uint64(block.timestamp)));
                _invariants();
            }
        }
        assertEq(custody.accountExposure(player), 0);
        assertEq(custody.accountActive(player), 0);
        assertEq(vault.openExposure(), 0);
    }

    function testUnauthorizedDustDepositsCannotConsumeBoundedCapacity() public {
        _deposit(alice, 1000e6);
        usdc.mint(bob, 64);
        vm.prank(bob);
        usdc.approve(address(vault), 64);
        for (uint256 i; i < 64; ++i) {
            DailyLPVault.DepositAuthorization memory a =
                DailyLPVault.DepositAuthorization(bob, 1, bytes32(i + 1), uint64(block.timestamp + 100));
            vm.prank(bob);
            vm.expectRevert(AccessController.InvalidSignature.selector);
            vault.deposit(a, hex"", hex"");
        }
        assertEq(vault.activeLots().length, 1);
        _deposit(bob, 1000e6);
        assertEq(vault.activeLots().length, 2);
        _invariants();
    }

    function testDepositAuthorizationBindsOwnerAmountExpiryVersionAndSingleUse() public {
        usdc.mint(bob, 1000);
        vm.prank(bob);
        usdc.approve(address(vault), 1000);
        DailyLPVault.DepositAuthorization memory a =
            DailyLPVault.DepositAuthorization(bob, 100, bytes32(uint256(888)), uint64(block.timestamp + 100));
        bytes32 digest = vault.hashDeposit(a);
        bytes memory s = _sign(SETTLEMENT_KEY, digest);
        bytes memory r = _sign(RISK_KEY, digest);
        a.amount = 101;
        vm.prank(bob);
        vm.expectRevert(AccessController.InvalidSignature.selector);
        vault.deposit(a, s, r);
        a.amount = 100;
        vm.prank(alice);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        vault.deposit(a, s, r);
        vm.prank(bob);
        vault.deposit(a, s, r);
        vm.prank(bob);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        vault.deposit(a, s, r);
        _invariants();
    }

    function testFinalVoidDeterminedNextDayUnblocksPriorCloseWithoutBackdatingOrEarlyRelease() public {
        uint256 lot = _deposit(alice, 1000);
        access.resumeTrading();
        _trade(100, 3);
        uint256 end = vault.cutoff();
        vm.warp(end - 60);
        bytes32 id = _accept(0, 1100, 2);
        vm.warp(end + 10);
        _resolve(_outcome(id, 4, uint64(block.timestamp)));
        assertEq(vault.openExposure(), 1100);
        assertEq(custody.totalLocked(), 1100);
        assertEq(vault.maxWithdrawal(lot), 0);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        custody.completeVoid(id);
        _submitClose(_closeReport(0));
        assertEq(vault.totalFees(), 0);
        assertEq(_lot(lot).mark, 0);
        assertEq(vault.openExposure(), 1100);
        access.pauseTrading();
        access.setSigner(access.RISK_SIGNER(), vm.addr(0x999));
        custody.completeVoid(id);
        assertEq(vault.openExposure(), 0);
        assertEq(custody.totalLocked(), 0);
        assertEq(vault.maxWithdrawal(lot), 1000);
        // Rotate back only for the next close authorization; recorded void needed none.
        access.setSigner(access.RISK_SIGNER(), vm.addr(RISK_KEY));
        _close(0);
        assertEq(vault.totalFees(), 5);
        _close(0);
        assertEq(vault.totalFees(), 5);
        vm.expectRevert(DailyBetCustody.InvalidAuthorization.selector);
        custody.completeVoid(id);
        _invariants();
    }

    function testFutureDayVoidKeepsReserveAcrossMultipleOverdueCloses() public {
        _deposit(alice, 1000);
        access.resumeTrading();
        uint256 end = vault.cutoff();
        vm.warp(end - 60);
        bytes32 id = _accept(0, 100, 2);
        uint64 canonical = uint64(end + 2 days + 10);
        vm.warp(canonical);
        _resolve(_outcome(id, 4, canonical));
        for (uint256 i; i < 3; ++i) {
            _submitClose(_closeReport(0));
            assertEq(vault.openExposure(), 100);
        }
        custody.completeVoid(id);
        assertEq(vault.openExposure(), 0);
        assertEq(custody.totalLocked(), 0);
        _invariants();
    }

    function testDepositExpiryRotationCrossVaultAndFailedTransferRollback() public {
        usdc.mint(bob, 1000);
        vm.prank(bob);
        usdc.approve(address(vault), 1000);
        DailyLPVault.DepositAuthorization memory a =
            DailyLPVault.DepositAuthorization(bob, 100, bytes32(uint256(999)), uint64(block.timestamp + 100));
        bytes32 digest = vault.hashDeposit(a);
        bytes memory s = _sign(SETTLEMENT_KEY, digest);
        bytes memory r = _sign(RISK_KEY, digest);
        vm.warp(block.timestamp + 101);
        vm.prank(bob);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        vault.deposit(a, s, r);
        a.deadline = uint64(block.timestamp + 1 hours + 1);
        vm.prank(bob);
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        vault.deposit(a, s, r);
        a.deadline = uint64(block.timestamp + 100);
        digest = vault.hashDeposit(a);
        s = _sign(SETTLEMENT_KEY, digest);
        r = _sign(RISK_KEY, digest);
        access.setSigner(access.RISK_SIGNER(), vm.addr(RISK_KEY));
        vm.prank(bob);
        vm.expectRevert(AccessController.InvalidSignature.selector);
        vault.deposit(a, s, r);
        digest = vault.hashDeposit(a);
        s = _sign(SETTLEMENT_KEY, digest);
        r = _sign(RISK_KEY, digest);
        _deploy(0, 0, 0);
        assertNotEq(vault.hashDeposit(a), digest);
        vm.prank(bob);
        usdc.approve(address(vault), 1000);
        vm.prank(bob);
        vm.expectRevert(AccessController.InvalidSignature.selector);
        vault.deposit(a, s, r);
        digest = vault.hashDeposit(a);
        s = _sign(SETTLEMENT_KEY, digest);
        r = _sign(RISK_KEY, digest);
        usdc.setTaxed(true);
        vm.prank(bob);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        vault.deposit(a, s, r);
        assertFalse(vault.usedDepositAuthorizations(a.id));
        assertEq(vault.activeLots().length, 0);
        usdc.setTaxed(false);
        vm.prank(bob);
        vault.deposit(a, s, r);
        assertTrue(vault.usedDepositAuthorizations(a.id));
        _invariants();
    }

    function testMillisecondBarrierHitMatchesSharedPapertradeClock() public {
        uint256 lot = _deposit(alice, 1000);
        access.resumeTrading();
        bytes32 id = _accept(0, 100, 2);
        DailyBetCustody.Outcome memory o = _outcome(id, 3, uint64(block.timestamp));
        o.canonicalTime += 123;
        vm.warp(block.timestamp + 1);
        _resolve(o);
        assertEq(_lot(lot).pnl, 100);
        assertEq(vault.openExposure(), 0);
        _invariants();
    }

    function testCloseTransferFailuresRetainReservationsAndCanRetryDuringPause() public {
        _deposit(alice, 2000);
        access.resumeTrading();
        _trade(1000, 3);
        uint64 day = _close(100);
        access.pauseTrading();
        uint256 cash = vault.accountedCash();
        uint256 fee = vault.operatorDue();
        uint256 backing = vault.backingDue();
        usdc.setTaxed(true);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        vault.payFee(day);
        vm.expectRevert(ExactTransfer.UnexpectedTransfer.selector);
        vault.payBacking(day);
        assertEq(vault.accountedCash(), cash);
        assertEq(vault.operatorDue(), fee);
        assertEq(vault.backingDue(), backing);
        (,,,, bool feePaid, bool backingPaid) = vault.closes(day);
        assertFalse(feePaid);
        assertFalse(backingPaid);
        usdc.setTaxed(false);
        vault.payFee(day);
        vault.payBacking(day);
        _invariants();
    }

    function _batch(DailyBetCustody.Outcome[] memory outcomes) internal {
        bytes32 journal = keccak256("shared-papertrade-journal");
        uint64 deadline = uint64(block.timestamp + 100);
        bytes32 digest = custody.hashBatch(outcomes, journal, deadline);
        custody.settleBatch(outcomes, journal, deadline, _sign(SETTLEMENT_KEY, digest), _sign(RISK_KEY, digest));
    }

    function _projection() internal view returns (bytes32) {
        return keccak256(
            abi.encode(
                vault.accountedCash(),
                vault.totalEquity(),
                vault.openExposure(),
                vault.totalRealized(),
                _lot(1),
                _lot(2),
                custody.totalAvailable(),
                custody.totalLocked(),
                custody.totalBonusReserved(),
                custody.available(player),
                custody.accountExposure(player),
                custody.accountActive(player),
                usdc.balanceOf(address(vault)),
                usdc.balanceOf(address(custody))
            )
        );
    }

    function testFuzzPaperStyleNetBatchEqualsIndividualSharedOutcomes(uint96 seed, uint8 count) public {
        _deposit(alice, 1_000_000e6);
        _deposit(bob, 1_000_000e6);
        access.resumeTrading();
        count = uint8(bound(count, 1, 16));
        DailyBetCustody.Outcome[] memory outcomes = new DailyBetCustody.Outcome[](count);
        uint256 entropy = seed;
        uint64 start = uint64(block.timestamp);
        int256 expected;
        for (uint256 i; i < count; ++i) {
            entropy = uint256(keccak256(abi.encode(entropy, i)));
            uint256 stake = 1 + entropy % 1000e6;
            uint256 multiplier = i % 3 == 0 ? 5 : 2;
            bytes32 id = _accept(uint8(i % 3), stake, multiplier);
            uint8 status = uint8(2 + entropy / 1000e6 % 3);
            outcomes[i] = _outcome(id, status, start + (status == 3 ? 1 : 30));
            expected += status == 3 ? int256(stake) : status == 2 ? -int256(stake * (multiplier - 1)) : int256(0);
        }
        vm.warp(block.timestamp + 30);
        uint256 snap = vm.snapshotState();
        uint256 cash = vault.accountedCash();
        access.pauseTrading();
        _batch(outcomes);
        assertEq(int256(vault.accountedCash()), int256(cash) + expected);
        bytes32 batchProjection = _projection();
        _invariants();
        assertTrue(vm.revertToState(snap));
        access.pauseTrading();
        for (uint256 i; i < count; ++i) {
            _resolve(outcomes[i]);
        }
        assertEq(_projection(), batchProjection);
        _invariants();
    }

    function testZeroNetBatchMovesNoUSDCAndKeepsEachOriginalOwnerPnL() public {
        _deposit(alice, 1000e6);
        _deposit(bob, 1000e6);
        access.resumeTrading();
        bytes32 win = _accept(0, 100e6, 2);
        bytes32 loss = _accept(1, 100e6, 2);
        DailyBetCustody.Outcome[] memory outcomes = new DailyBetCustody.Outcome[](2);
        outcomes[0] = _outcome(win, 2, uint64(block.timestamp + 30));
        outcomes[1] = _outcome(loss, 3, uint64(block.timestamp + 1));
        vm.warp(block.timestamp + 30);
        usdc.setTaxed(true); // Any gross token transfer would revert ExactTransfer.
        _batch(outcomes);
        assertEq(vault.accountedCash(), 2000e6);
        assertEq(vault.totalRealized(), 0);
        assertEq(_lot(1).pnl, 0);
        assertEq(_lot(2).pnl, 0);
        assertEq(custody.totalLocked(), 0);
        _invariants();
    }

    function testBatchDuplicateOrInvalidOutcomeRollsBackEveryTicketAndNetTransfer() public {
        _deposit(alice, 1000e6);
        access.resumeTrading();
        bytes32 first = _accept(0, 100e6, 2);
        bytes32 second = _accept(1, 100e6, 2);
        DailyBetCustody.Outcome[] memory outcomes = new DailyBetCustody.Outcome[](2);
        outcomes[0] = _outcome(first, 3, uint64(block.timestamp + 1));
        outcomes[1] = outcomes[0];
        vm.warp(block.timestamp + 30);
        bytes32 beforeState = _projection();
        vm.expectRevert(DailyBetCustody.InvalidAuthorization.selector);
        this.batchFromTest(outcomes);
        assertEq(_projection(), beforeState);
        outcomes[1] = _outcome(second, 3, uint64(block.timestamp)); // hit exactly at expiry is invalid
        vm.expectRevert(DailyLPVault.InvalidAction.selector);
        this.batchFromTest(outcomes);
        assertEq(_projection(), beforeState);
        outcomes[1].canonicalTime -= 1;
        _batch(outcomes);
        vm.expectRevert(DailyBetCustody.InvalidAuthorization.selector);
        this.batchFromTest(outcomes);
        _invariants();
    }

    function batchFromTest(DailyBetCustody.Outcome[] memory outcomes) external {
        _batch(outcomes);
    }

    function testOnchainBetMarketAccountAndGlobalLimitsRejectAtOneAtomicUnit() public {
        _deposit(alice, 3_000_000e6);
        access.resumeTrading();
        vm.expectRevert(DailyLPVault.InsufficientCapital.selector);
        this.acceptSpecific(0, 1_000_000e6 + 1);
        _accept(0, 1_000_000e6, 2);
        _accept(0, 1_000_000e6, 2);
        vm.expectRevert(DailyBetCustody.InsufficientBalance.selector);
        this.acceptSpecific(1, 1);
        player = address(0xC0FFEE);
        _fundCustomer(player, 3_000_000e6);
        vm.expectRevert(DailyLPVault.InsufficientCapital.selector);
        this.acceptSpecific(0, 1);
        _accept(1, 1_000_000e6, 2);
        vm.expectRevert(DailyLPVault.InsufficientCapital.selector);
        this.acceptSpecific(2, 1);
        assertEq(vault.openExposure(), 3_000_000e6);
        assertEq(vault.marketExposure(0), 2_000_000e6);
        assertEq(vault.marketExposure(1), 1_000_000e6);
        _invariants();
    }

    function acceptSpecific(uint8 asset, uint256 stake) external {
        _accept(asset, stake, 2);
    }

    function testAcceptedOutcomesReserveNumericHeadroomAtMoneyBoundary() public {
        uint256 maximum = vault.MAX_MONEY();
        uint256 lot = _deposit(alice, maximum);
        access.resumeTrading();
        vm.expectRevert(DailyLPVault.InsufficientCapital.selector);
        this.acceptSpecific(0, 1);
        vm.prank(alice);
        vault.withdraw(lot, 1);
        bytes32 id = _accept(0, 1, 2);
        assertEq(vault.totalEquity() + vault.openStakeProfit(), maximum);
        vm.warp(block.timestamp + 30);
        _resolve(_outcome(id, 3, uint64(block.timestamp - 1)));
        assertEq(vault.totalEquity(), maximum);
        assertEq(vault.openStakeProfit(), 0);
        _invariants();
    }

    function testCustodyReservesAllWinningCreditsBeforeAcceptingAtMoneyBoundary() public {
        _deposit(alice, 1000);
        uint256 maximum = vault.MAX_MONEY();
        _fundCustomer(player, maximum - custody.totalAvailable());
        access.resumeTrading();
        vm.expectRevert(DailyBetCustody.InsufficientBalance.selector);
        this.acceptSpecific(0, 1);
        vm.prank(player);
        custody.withdraw(1);
        bytes32 id = _accept(0, 1, 2);
        assertEq(custody.totalAvailable() + custody.totalLocked() + custody.totalBonusReserved(), maximum);
        vm.warp(block.timestamp + 30);
        _resolve(_outcome(id, 2, uint64(block.timestamp)));
        assertEq(custody.totalAvailable(), maximum);
        assertEq(custody.totalBonusReserved(), 0);
        _invariants();
    }

    function testBounded64LotAnd16OutcomeGasCosts() public {
        for (uint256 i; i < 64; ++i) {
            _deposit(address(uint160(1000 + i)), 1000);
        }
        access.resumeTrading();
        DailyBetCustody.Outcome[] memory outcomes = new DailyBetCustody.Outcome[](16);
        uint64 start = uint64(block.timestamp);
        for (uint256 i; i < 16; ++i) {
            uint256 beforeGas = gasleft();
            bytes32 id = _accept(uint8(i % 3), 64, 2);
            if (i == 0) emit log_named_uint("64-lot signed acceptance gas", beforeGas - gasleft());
            outcomes[i] = _outcome(id, uint8(i % 2 == 0 ? 2 : 3), start + (i % 2 == 0 ? 30 : 1));
        }
        vm.warp(block.timestamp + 30);
        uint256 beforeBatch = gasleft();
        _batch(outcomes);
        emit log_named_uint("64-lot 16-outcome signed net batch gas", beforeBatch - gasleft());
        _trade(1280, 3);
        uint256 end = vault.cutoff();
        vm.warp(end);
        uint256 beforeClose = gasleft();
        _submitClose(_closeReport(28));
        emit log_named_uint("64-lot signed close with 63 charge remainders gas", beforeClose - gasleft());
        _invariants();
    }
}
