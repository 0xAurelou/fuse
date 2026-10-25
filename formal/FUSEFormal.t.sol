// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "../test/helpers/FUSEFixture.sol";
import {CustomerCustodyVault} from "../src/CustomerCustodyVault.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {WithdrawalGateway} from "../src/WithdrawalGateway.sol";
import {LPVault} from "../src/LPVault.sol";
import {AccessController} from "../src/AccessController.sol";
import {MockUSDC} from "../test/helpers/FUSEFixture.sol";
import {FUSEToken} from "../src/FUSEToken.sol";
import {RewardDistributor} from "../src/RewardDistributor.sol";
import {RedemptionReserve} from "../src/RedemptionReserve.sol";
import {ISettlementView} from "../src/interfaces/ISettlementView.sol";
import {Module} from "../src/common/Module.sol";
import {TreasuryEscrow} from "../src/AllocationEscrows.sol";

import {IERC1271} from "@openzeppelin/contracts/interfaces/IERC1271.sol";

/// @dev Test-only authority approving only the selected digest; assumes unforgeable signatures.
contract FormalSigner is IERC1271 {
    mapping(bytes32 => bool) private approved;

    function approve(bytes32 digest) external {
        approved[digest] = true;
    }

    function isValidSignature(bytes32 digest, bytes memory) external view returns (bytes4) {
        return approved[digest] ? IERC1271.isValidSignature.selector : bytes4(0);
    }
}

/// @notice Bounded symbolic execution of production bytecode. See docs/FORMAL_VERIFICATION.md.
/// @dev Real protocol modules, exact-transfer mock USDC and digest-specific ERC-1271 authorities.
contract FUSEFormal is FUSEFixture {
    uint256 private constant MAX_USDC = 100_000e6;

    FormalSigner private settlementSigner;
    FormalSigner private riskSigner;
    FormalSigner private withdrawalSigner;

    function setUp() public {
        vm.warp(1_700_000_000);
        alice = address(0xA11CE);
        access = new AccessController(address(this));
        usdc = new MockUSDC();
        custody = new CustomerCustodyVault(access, usdc, 1 days);
        lp = new LPVault(access, usdc);
        controller = new SettlementController(access, custody, lp);
        gateway = new WithdrawalGateway(access, custody, ISettlementView(address(controller)));
        token = new FUSEToken(access, 2 days);
        rewards = new RewardDistributor(access, token);
        reserve = new RedemptionReserve(access, usdc, token, address(lp));
        custody.configure(address(controller), address(gateway), address(lp));
        lp.configure(address(custody), ISettlementView(address(controller)), address(reserve));
        token.setRedemptionReserve(address(reserve));
        token.emissionEscrow().setDistributor(address(rewards));
        access.grantRole(access.LP_PROVIDER(), address(this));
        access.grantRole(access.EMISSION_PUBLISHER(), address(this));
        access.grantRole(access.REDEMPTION_SCHEDULER(), address(this));
        access.grantRole(access.GUARDIAN(), address(this));
        usdc.mint(address(this), 1e18);
        usdc.approve(address(custody), type(uint256).max);
        usdc.approve(address(lp), type(uint256).max);
        lp.depositLP(1_000_000e6);
        settlementSigner = new FormalSigner();
        riskSigner = new FormalSigner();
        withdrawalSigner = new FormalSigner();
        access.setSigner(access.SETTLEMENT_SIGNER(), address(settlementSigner));
        access.setSigner(access.RISK_SIGNER(), address(riskSigner));
        access.setSigner(access.WITHDRAWAL_SIGNER(), address(withdrawalSigner));
    }

    function _amount(uint256 amount) private pure {
        vm.assume(amount > 0 && amount <= MAX_USDC);
    }

    /// @dev Assert successful calls so a surprising revert cannot silently discard a proof path.
    function _mustCall(address target, bytes memory data) private returns (bytes memory result) {
        bool ok;
        (ok, result) = target.call(data);
        assert(ok);
    }

    function _mustReject(address target, bytes memory data, bytes4 expected) private {
        (bool ok, bytes memory result) = target.call(data);
        assert(!ok);
        assert(result.length >= 4 && bytes4(result) == expected);
    }

    function _deposit(uint256 amount) private returns (uint256) {
        return abi.decode(_mustCall(address(custody), abi.encodeCall(custody.deposit, (amount, alice))), (uint256));
    }

    function _executeReport(SettlementController.EpochSettlement memory report, uint256[] memory ids) private {
        bytes32 digest = controller.hashSettlement(report);
        settlementSigner.approve(digest);
        riskSigner.approve(digest);
        _mustCall(address(controller), abi.encodeCall(controller.settle, (report, ids, bytes(""), bytes(""))));
    }

    function _creditFunds(uint256 amount) private {
        uint256 id = _deposit(amount);
        _executeReport(_report(0, custody.customerLiabilityUSDC() + amount, _ids(id)), _ids(id));
    }

    function check_deposit_credit_excludes_refund(uint64 amount) public {
        _amount(amount);
        _creditFunds(amount);
        vm.warp(block.timestamp + 1 days);
        _mustReject(
            address(custody),
            abi.encodeCall(custody.refundUncreditedDeposit, (1)),
            CustomerCustodyVault.InvalidDeposit.selector
        );
        (,,,,, CustomerCustodyVault.DepositStatus status) = custody.deposits(1);
        assert(status == CustomerCustodyVault.DepositStatus.Credited);
        assert(custody.uncreditedBalance() == 0);
        assert(usdc.balanceOf(address(custody)) == amount);
    }

    function check_deposit_refund_excludes_credit(uint64 amount) public {
        _amount(amount);
        uint256 initialBalance = usdc.balanceOf(address(this));
        uint256 id = _deposit(amount);
        vm.warp(block.timestamp + 1 days);
        vm.prank(bob);
        _mustCall(address(custody), abi.encodeCall(custody.refundUncreditedDeposit, (id)));
        SettlementController.EpochSettlement memory report = _report(0, 0, _ids(id));
        bytes32 digest = controller.hashSettlement(report);
        settlementSigner.approve(digest);
        riskSigner.approve(digest);
        _mustReject(
            address(controller),
            abi.encodeCall(controller.settle, (report, _ids(id), bytes(""), bytes(""))),
            CustomerCustodyVault.InvalidDeposit.selector
        );
        assert(usdc.balanceOf(address(this)) == initialBalance);
        assert(usdc.balanceOf(bob) == 0);
        assert(custody.uncreditedBalance() == 0);
        assert(controller.latestEpoch() == 0);
    }

    function _rejectReport(SettlementController.EpochSettlement memory report, uint256[] memory ids, bytes4 expected)
        private
    {
        bytes32 digest = controller.hashSettlement(report);
        settlementSigner.approve(digest);
        riskSigner.approve(digest);
        _mustReject(
            address(controller), abi.encodeCall(controller.settle, (report, ids, bytes(""), bytes(""))), expected
        );
    }

    function check_pending_deposit_cannot_fund_lp(uint64 amount) public {
        _amount(amount);
        _deposit(amount);
        uint256 beforeLP = usdc.balanceOf(address(lp));
        uint256[] memory ids = new uint256[](0);
        _rejectReport(_report(-int256(uint256(amount)), 0, ids), ids, CustomerCustodyVault.InsufficientBacking.selector);
        assert(custody.uncreditedBalance() == amount);
        assert(usdc.balanceOf(address(custody)) == amount);
        assert(usdc.balanceOf(address(lp)) == beforeLP);
        assert(controller.latestEpoch() == 0);
    }

    function check_net_settlement_conserves_usdc(uint64 depositAmount, uint64 pnl, bool traderWins) public {
        _amount(depositAmount);
        _amount(pnl);
        vm.assume(traderWins || pnl <= depositAmount);
        _creditFunds(depositAmount);
        uint256 total = usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp));
        uint256 liability = traderWins ? uint256(depositAmount) + pnl : uint256(depositAmount) - pnl;
        int256 net = traderWins ? int256(uint256(pnl)) : -int256(uint256(pnl));
        uint256[] memory ids = new uint256[](0);
        _executeReport(_report(net, liability, ids), ids);
        assert(usdc.balanceOf(address(custody)) + usdc.balanceOf(address(lp)) == total);
        assert(custody.customerLiabilityUSDC() == liability);
        assert(usdc.balanceOf(address(custody)) == liability);
        assert(lp.accountedBalance() == usdc.balanceOf(address(lp)));
    }

    function check_underfunded_settlement_is_atomic(uint64 amount) public {
        _amount(amount);
        uint256 id = _deposit(amount);
        uint256 balanceLP = usdc.balanceOf(address(lp));
        _rejectReport(
            _report(-int256(uint256(amount)), 1, _ids(id)), _ids(id), CustomerCustodyVault.InsufficientBacking.selector
        );
        (,,,,, CustomerCustodyVault.DepositStatus status) = custody.deposits(id);
        assert(status == CustomerCustodyVault.DepositStatus.Pending);
        assert(custody.uncreditedBalance() == amount);
        assert(usdc.balanceOf(address(custody)) == amount);
        assert(usdc.balanceOf(address(lp)) == balanceLP);
        assert(lp.cumulativeRealizedProfitUSDC() == 0);
        assert(controller.latestEpoch() == 0);
        assert(controller.currentRoot() == bytes32(0));
    }

    function check_epoch_cannot_execute_twice(uint64 amount) public {
        _amount(amount);
        uint256 id = _deposit(amount);
        SettlementController.EpochSettlement memory report = _report(0, amount, _ids(id));
        _executeReport(report, _ids(id));
        _rejectReport(report, _ids(id), SettlementController.InvalidCheckpoint.selector);
        assert(controller.latestEpoch() == 1);
        assert(custody.customerLiabilityUSDC() == amount);
    }

    function check_settlement_requires_independent_risk(uint64 amount) public {
        _amount(amount);
        uint256 id = _deposit(amount);
        SettlementController.EpochSettlement memory report = _report(0, amount, _ids(id));
        settlementSigner.approve(controller.hashSettlement(report));
        _mustReject(
            address(controller),
            abi.encodeCall(controller.settle, (report, _ids(id), bytes(""), bytes(""))),
            AccessController.InvalidSignature.selector
        );
        assert(controller.latestEpoch() == 0);
        assert(custody.uncreditedBalance() == amount);
    }

    function _claimFunds(WithdrawalGateway.WithdrawalAuthorization memory authorization) private {
        withdrawalSigner.approve(gateway.hashWithdrawal(authorization));
        _mustCall(address(gateway), abi.encodeCall(gateway.claim, (authorization, bytes(""), bytes(""))));
    }

    function check_cumulative_withdrawal_pays_only_delta(uint64 first, uint64 increment) public {
        _amount(first);
        _amount(increment);
        uint256 total = uint256(first) + increment;
        _creditFunds(total);
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(alice, alice, first, bytes32(uint256(1)));
        _claimFunds(a);
        _claimFunds(_authorization(alice, alice, total, bytes32(uint256(2))));
        _mustReject(
            address(gateway),
            abi.encodeCall(gateway.claim, (a, bytes(""), bytes(""))),
            WithdrawalGateway.InvalidAuthorization.selector
        );
        assert(gateway.withdrawnCumulative(alice) == total);
        assert(usdc.balanceOf(alice) == total);
        assert(custody.customerLiabilityUSDC() == 0);
        assert(usdc.balanceOf(address(custody)) == 0);
    }

    function check_operator_cannot_redirect_withdrawal(uint64 amount) public {
        _amount(amount);
        _creditFunds(amount);
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(alice, bob, amount, bytes32(uint256(1)));
        withdrawalSigner.approve(gateway.hashWithdrawal(a));
        _mustReject(
            address(gateway),
            abi.encodeCall(gateway.claim, (a, bytes(""), bytes(""))),
            WithdrawalGateway.RecipientNotAuthorized.selector
        );
        assert(gateway.withdrawnCumulative(alice) == 0);
        assert(!gateway.usedAuthorizations(a.authorizationId));
        assert(usdc.balanceOf(bob) == 0);
        assert(custody.customerLiabilityUSDC() == amount);
    }

    function check_signer_rotation_invalidates_authorization(uint64 amount) public {
        _amount(amount);
        _creditFunds(amount);
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(alice, alice, amount, bytes32(uint256(1)));
        withdrawalSigner.approve(gateway.hashWithdrawal(a));
        access.setSigner(access.WITHDRAWAL_SIGNER(), address(withdrawalSigner));
        _mustReject(
            address(gateway),
            abi.encodeCall(gateway.claim, (a, bytes(""), bytes(""))),
            AccessController.InvalidSignature.selector
        );
        assert(gateway.withdrawnCumulative(alice) == 0);
        assert(custody.customerLiabilityUSDC() == amount);
    }

    function check_guardian_pause_preserves_funded_claims(uint64 amount) public {
        _amount(amount);
        _creditFunds(amount);
        access.pauseTrading();
        _mustReject(address(custody), abi.encodeCall(custody.deposit, (amount, alice)), Module.TradingPaused.selector);
        _claimFunds(_authorization(alice, alice, amount, bytes32(uint256(1))));
        assert(usdc.balanceOf(alice) == amount);
        assert(custody.customerLiabilityUSDC() == 0);
    }

    /// @custom:halmos --loop 32
    function check_reentrant_token_cannot_duplicate_withdrawal(uint64 amount) public {
        _amount(amount);
        _creditFunds(amount);
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(alice, alice, amount, bytes32(uint256(1)));
        // The larger loop bound covers copying this fixed-size callback payload to/from mock storage.
        usdc.setCallback(address(gateway), abi.encodeCall(gateway.claim, (a, bytes(""), bytes(""))));
        _claimFunds(a);
        assert(!usdc.callbackSucceeded());
        assert(usdc.balanceOf(alice) == amount);
        assert(gateway.withdrawnCumulative(alice) == amount);
        assert(custody.customerLiabilityUSDC() == 0);
        assert(gateway.usedAuthorizations(a.authorizationId));
    }

    function _grantReward(address recipient, uint256 amount) private {
        _startRewards();
        bytes32 root = rewards.rewardLeaf(1, 257, recipient, amount);
        _mustCall(
            address(rewards), abi.encodeCall(rewards.publishEpoch, (uint64(1), root, amount, keccak256("manifest")))
        );
        _mustCall(
            address(rewards), abi.encodeCall(rewards.claim, (uint64(1), 257, recipient, amount, new bytes32[](0)))
        );
    }

    function check_reward_budget_and_bitmap_replay(uint96 amount) public {
        vm.assume(amount > 0 && amount <= token.EMISSION_ALLOCATION());
        _grantReward(alice, amount);
        _mustReject(
            address(rewards),
            abi.encodeCall(rewards.claim, (uint64(1), 257, alice, amount, new bytes32[](0))),
            RewardDistributor.InvalidClaim.selector
        );
        assert(rewards.isClaimed(1, 257));
        assert(!rewards.isClaimed(1, 1));
        assert(rewards.totalClaimed() == amount);
        assert(rewards.totalAllocated() == amount);
        assert(token.balanceOf(alice) == amount);
        assert(token.balanceOf(address(token.emissionEscrow())) + amount == token.EMISSION_ALLOCATION());
        assert(token.totalSupply() == token.GENESIS_SUPPLY());
    }

    function check_reward_global_allocation_cap(uint96 first, uint96 second) public {
        vm.assume(first > 0 && first <= token.EMISSION_ALLOCATION());
        vm.assume(second > 0 && second <= token.EMISSION_ALLOCATION());
        _startRewards();
        _mustCall(
            address(rewards),
            abi.encodeCall(rewards.publishEpoch, (uint64(1), bytes32(uint256(1)), first, bytes32(uint256(1))))
        );
        vm.warp(block.timestamp + 1 days);
        bytes memory data =
            abi.encodeCall(rewards.publishEpoch, (uint64(2), bytes32(uint256(2)), second, bytes32(uint256(2))));
        if (second > rewards.nextEpochCap() || uint256(first) + second > token.EMISSION_ALLOCATION()) {
            _mustReject(address(rewards), data, RewardDistributor.InvalidEpoch.selector);
            assert(rewards.totalAllocated() == first);
        } else {
            _mustCall(address(rewards), data);
            assert(rewards.totalAllocated() == uint256(first) + second);
        }
        assert(rewards.totalAllocated() <= token.EMISSION_ALLOCATION());
    }

    function check_users_cannot_transfer_before_activation(uint96 amount) public {
        vm.assume(amount > 0 && amount <= token.EMISSION_ALLOCATION());
        _grantReward(alice, amount);
        vm.prank(alice);
        _mustReject(address(token), abi.encodeCall(token.transfer, (bob, amount)), FUSEToken.TransfersDisabled.selector);
        assert(token.balanceOf(alice) == amount);
        assert(token.balanceOf(bob) == 0);
    }

    function _fundReserveApproved(uint256 amount) private {
        LPVault.ReserveAuthorization memory a = _reserveAuthorization(amount);
        bytes32 digest = lp.hashReserveAuthorization(a);
        settlementSigner.approve(digest);
        riskSigner.approve(digest);
        _mustCall(address(lp), abi.encodeCall(lp.fundFUSEReserve, (a, bytes(""), bytes(""))));
    }

    function check_distributed_profit_cannot_be_reused(uint64 attempt) public {
        _amount(attempt);
        uint256 profit = 1000e6;
        uint256 distribution = 350e6;
        uint256 id = _deposit(profit);
        _executeReport(_report(-int256(profit), 0, _ids(id)), _ids(id));
        uint256 beforeLP = usdc.balanceOf(address(lp));
        _fundReserveApproved(distribution);
        assert(lp.consumedProfitHWMUSDC() == profit);
        assert(usdc.balanceOf(address(reserve)) == distribution);
        assert(usdc.balanceOf(address(lp)) + distribution == beforeLP);
        LPVault.ReserveAuthorization memory a = _reserveAuthorization(attempt);
        bytes32 digest = lp.hashReserveAuthorization(a);
        settlementSigner.approve(digest);
        riskSigner.approve(digest);
        _mustReject(
            address(lp),
            abi.encodeCall(lp.fundFUSEReserve, (a, bytes(""), bytes(""))),
            LPVault.InvalidReserveAuthorization.selector
        );
        assert(lp.reserveDistributedUSDC() == distribution);
        assert(lp.accountedBalance() == usdc.balanceOf(address(lp)));
    }

    function _prepareRedemption(uint256 rewardAmount) private {
        uint256 id = _deposit(1000e6);
        _executeReport(_report(-1000e6, 0, _ids(id)), _ids(id));
        _fundReserveApproved(350e6);
        _grantReward(alice, rewardAmount);
        reserve.activateRedemptions();
        reserve.openRedemptionEpoch(uint64(block.timestamp), uint64(block.timestamp + 1 days), 1000);
        vm.prank(alice);
        token.approve(address(reserve), type(uint256).max);
    }

    function _redeem(uint256 amount) private {
        vm.prank(alice);
        _mustCall(address(reserve), abi.encodeCall(reserve.requestRedeem, (amount)));
    }

    function _redemptionAccount(address account) private {
        vm.assume(
            account != address(0) && account != address(this) && account != address(lp) && account != address(custody)
                && account != address(reserve) && account != address(token.emissionEscrow())
                && account != address(token.treasuryEscrow())
        );
        alice = account;
    }

    function check_redemption_burn_and_backing(address account) public {
        _redemptionAccount(account);
        uint256 amount = 10_000_007 ether;
        _prepareRedemption(amount);
        _redeem(amount);
        uint256 expected = 3_150_002;
        assert(token.totalSupply() + amount == token.GENESIS_SUPPLY());
        assert(reserve.outstandingUSDC() == expected);
        assert(usdc.balanceOf(address(reserve)) >= reserve.outstandingUSDC());
        vm.warp(block.timestamp + 1 days);
        vm.prank(alice);
        _mustCall(address(reserve), abi.encodeCall(reserve.claimRedeemedUSDC, (uint64(1))));
        assert(usdc.balanceOf(alice) == expected);
        assert(reserve.outstandingUSDC() == 0);
        vm.prank(alice);
        _mustReject(
            address(reserve),
            abi.encodeCall(reserve.claimRedeemedUSDC, (uint64(1))),
            RedemptionReserve.InvalidRequest.selector
        );
    }

    function check_redemption_splitting_same_account(address account, bool reverseOrder) public {
        _redemptionAccount(account);
        uint256 first = 10_000_007 ether;
        uint256 second = 20_000_009 ether;
        uint256 total = first + second;
        _prepareRedemption(total);
        _redeem(reverseOrder ? second : first);
        _redeem(reverseOrder ? first : second);
        (, uint256 accrued,) = reserve.requests(1, alice);
        assert(accrued == 9_450_005);
        assert(reserve.outstandingUSDC() == accrued);
        assert(token.totalSupply() + total == token.GENESIS_SUPPLY());
    }

    function check_next_redemption_epoch_excludes_prior_claims(address account) public {
        _redemptionAccount(account);
        _prepareRedemption(10_000_007 ether);
        _redeem(10_000_007 ether);
        uint256 pending = reserve.outstandingUSDC();
        vm.warp(block.timestamp + 1 days);
        _mustCall(
            address(reserve),
            abi.encodeCall(
                reserve.openRedemptionEpoch, (uint64(block.timestamp), uint64(block.timestamp + 1 days), uint16(1000))
            )
        );
        (,,,, uint256 supply, uint256 available,,) = reserve.epochs(2);
        assert(available + pending == usdc.balanceOf(address(reserve)));
        assert(supply == token.totalSupply());
        assert(usdc.balanceOf(address(reserve)) >= pending);
    }

    function check_treasury_locked_without_approved_policy(uint96 amount) public {
        vm.assume(amount > 0 && amount <= token.TREASURY_ALLOCATION());
        token.scheduleEnableTransfers();
        vm.warp(block.timestamp + 2 days);
        _mustCall(address(token), abi.encodeCall(token.enableTransfers, ()));
        TreasuryEscrow treasury = token.treasuryEscrow();
        _mustReject(
            address(treasury),
            abi.encodeCall(treasury.claim, (0, alice, amount, new bytes32[](0))),
            TreasuryEscrow.InvalidClaim.selector
        );
        assert(treasury.totalReleased() == 0);
        assert(token.balanceOf(address(treasury)) == token.TREASURY_ALLOCATION());
    }

    function check_transfer_activation_delay_and_irreversibility(uint32 elapsed) public {
        vm.assume(elapsed < 2 days);
        token.scheduleEnableTransfers();
        uint256 ready = token.transfersEnableAfter();
        vm.warp(block.timestamp + elapsed);
        _mustReject(address(token), abi.encodeCall(token.enableTransfers, ()), FUSEToken.ActivationNotReady.selector);
        assert(!token.transfersEnabled());
        vm.warp(ready);
        _mustCall(address(token), abi.encodeCall(token.enableTransfers, ()));
        _mustReject(
            address(token), abi.encodeCall(token.scheduleEnableTransfers, ()), FUSEToken.ActivationNotReady.selector
        );
        assert(token.transfersEnabled());
    }

    function check_reserve_funding_preserves_required_capital(uint64 amount) public {
        vm.assume(amount > 0 && amount <= 350e6);
        uint256 id = _deposit(1000e6);
        _executeReport(_report(-1000e6, 0, _ids(id)), _ids(id));
        uint256 beforeLP = usdc.balanceOf(address(lp));
        LPVault.ReserveAuthorization memory a = _reserveAuthorization(amount);
        a.minLPCapitalUSDC = beforeLP;
        bytes32 digest = lp.hashReserveAuthorization(a);
        settlementSigner.approve(digest);
        riskSigner.approve(digest);
        _mustReject(
            address(lp),
            abi.encodeCall(lp.fundFUSEReserve, (a, bytes(""), bytes(""))),
            LPVault.InsufficientCapital.selector
        );
        assert(usdc.balanceOf(address(lp)) == beforeLP);
        assert(usdc.balanceOf(address(reserve)) == 0);
        assert(lp.consumedProfitHWMUSDC() == 0);
        assert(!lp.usedReserveAuthorizations(a.authorizationId));
    }

    function check_reserve_cannot_underwrite_lp_payout(uint64 reserveDonation) public {
        _amount(reserveDonation);
        usdc.mint(address(reserve), reserveDonation);
        uint256 balanceLP = usdc.balanceOf(address(lp));
        uint256[] memory ids = new uint256[](0);
        _rejectReport(_report(int256(balanceLP + 1), balanceLP + 1, ids), ids, LPVault.InvalidSettlement.selector);
        assert(usdc.balanceOf(address(reserve)) == reserveDonation);
        assert(usdc.balanceOf(address(lp)) == balanceLP);
        assert(controller.latestEpoch() == 0);
    }
}
