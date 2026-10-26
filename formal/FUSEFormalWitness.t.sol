// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFormal} from "./FUSEFormal.t.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Concrete successful witnesses supplement the symbolic gate's non-vacuity checks.
contract FormalWitness is Test {
    FUSEFormal private proof;

    function setUp() public {
        proof = new FUSEFormal();
        proof.setUp();
    }

    function test_check_deposit_credit_excludes_refund() public {
        proof.check_deposit_credit_excludes_refund(100e6);
    }

    function test_check_deposit_refund_excludes_credit() public {
        proof.check_deposit_refund_excludes_credit(100e6);
    }

    function test_check_pending_deposit_cannot_fund_lp() public {
        proof.check_pending_deposit_cannot_fund_lp(100e6);
    }

    function test_check_net_settlement_conserves_usdc() public {
        proof.check_net_settlement_conserves_usdc(100e6, 10e6, true);
    }

    function test_check_underfunded_settlement_is_atomic() public {
        proof.check_underfunded_settlement_is_atomic(100e6);
    }

    function test_check_epoch_cannot_execute_twice() public {
        proof.check_epoch_cannot_execute_twice(100e6);
    }

    function test_check_settlement_requires_independent_risk() public {
        proof.check_settlement_requires_independent_risk(100e6);
    }

    function test_check_cumulative_withdrawal_pays_only_delta() public {
        proof.check_cumulative_withdrawal_pays_only_delta(100e6, 50e6);
    }

    function test_check_operator_cannot_redirect_withdrawal() public {
        proof.check_operator_cannot_redirect_withdrawal(100e6);
    }

    function test_check_signer_rotation_invalidates_authorization() public {
        proof.check_signer_rotation_invalidates_authorization(100e6);
    }

    function test_check_guardian_pause_preserves_funded_claims() public {
        proof.check_guardian_pause_preserves_funded_claims(100e6);
    }

    function test_check_reentrant_token_cannot_duplicate_withdrawal() public {
        proof.check_reentrant_token_cannot_duplicate_withdrawal(100e6);
    }

    function test_check_reward_budget_and_bitmap_replay() public {
        proof.check_reward_budget_and_bitmap_replay(100 ether);
    }

    function test_check_reward_global_allocation_cap() public {
        proof.check_reward_global_allocation_cap(400_000_000 ether, 300_000_000 ether);
    }

    function test_check_users_cannot_transfer_before_activation() public {
        proof.check_users_cannot_transfer_before_activation(100 ether);
    }

    function test_check_distributed_profit_cannot_be_reused() public {
        proof.check_distributed_profit_cannot_be_reused(1e6);
    }

    function test_check_redemption_burn_and_backing() public {
        proof.check_redemption_burn_and_backing(address(0xA11CE));
    }

    function test_check_redemption_splitting_same_account() public {
        proof.check_redemption_splitting_same_account(address(0xA11CE), true);
    }

    function test_check_next_redemption_epoch_excludes_prior_claims() public {
        proof.check_next_redemption_epoch_excludes_prior_claims(address(0xA11CE));
    }

    function test_check_treasury_locked_without_approved_policy() public {
        proof.check_treasury_locked_without_approved_policy(100 ether);
    }

    function test_check_transfer_activation_delay_and_irreversibility() public {
        proof.check_transfer_activation_delay_and_irreversibility(1 days);
    }

    function test_check_reserve_funding_preserves_required_capital() public {
        proof.check_reserve_funding_preserves_required_capital(100e6);
    }

    function test_check_reserve_cannot_underwrite_lp_payout() public {
        proof.check_reserve_cannot_underwrite_lp_payout(100e6);
    }

    function test_check_lp_deposit_issues_proportional_shares() public {
        proof.check_lp_deposit_issues_proportional_shares(address(0xB0B));
    }

    function test_check_lp_redeem_cannot_skip_request() public {
        proof.check_lp_redeem_cannot_skip_request(100e6);
    }

    function test_check_lp_profit_allocation_capped_at_35_percent() public {
        proof.check_lp_profit_allocation_capped_at_35_percent(5000);
    }
}
