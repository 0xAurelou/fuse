// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {WithdrawalGateway} from "../src/WithdrawalGateway.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {LPVault} from "../src/LPVault.sol";
import {RewardDistributor} from "../src/RewardDistributor.sol";
import {LPShareVault} from "../src/LPShareVault.sol";
import {LPIncentiveDistributor} from "../src/LPIncentiveDistributor.sol";

/// @dev Shared golden vectors also checked by engine/internal/contracts/typed_test.go.
contract EngineEncodingVectorsTest is FUSEFixture {
    address private constant VECTOR_MODULE = 0x1111111111111111111111111111111111111111;
    address private constant VECTOR_ACCOUNT = 0x2222222222222222222222222222222222222222;
    address private constant VECTOR_RECIPIENT = 0x3333333333333333333333333333333333333333;

    function setUp() public {
        _deploy();
        vm.chainId(998);
        while (access.signatureVersion() < 9) {
            access.setSigner(access.WITHDRAWAL_SIGNER(), vm.addr(WITHDRAWAL_KEY));
        }
    }

    function testGoWithdrawalVectorMatchesActualContract() public {
        vm.etch(VECTOR_MODULE, address(gateway).code);
        WithdrawalGateway.WithdrawalAuthorization memory a = WithdrawalGateway.WithdrawalAuthorization({
            account: VECTOR_ACCOUNT,
            recipient: VECTOR_RECIPIENT,
            cumulativeAmountUSDC: 123456789,
            stateVersion: 7,
            validUntil: 1800000000,
            authorizationId: bytes32(uint256(4)),
            accountStateHash: bytes32(uint256(5))
        });
        assertEq(
            WithdrawalGateway(VECTOR_MODULE).hashWithdrawal(a),
            0xd58bacb85daccd3196b1b2a1fb18eb35431e9902fd8f9ff0f0e9fddcd0ae26d7
        );
    }

    function testGoSettlementVectorMatchesActualContract() public {
        vm.etch(VECTOR_MODULE, address(controller).code);
        uint256[] memory ids = new uint256[](3);
        ids[0] = 1;
        ids[1] = 2;
        ids[2] = 300;
        assertEq(keccak256(abi.encode(ids)), 0x1a0641ced89f9d796418b109f69cdaa54f5b8327152fbff9943102d6d9216932);
        SettlementController.EpochSettlement memory s = SettlementController.EpochSettlement({
            epoch: 7,
            priorRoot: bytes32(uint256(1)),
            newRoot: bytes32(uint256(2)),
            journalHash: bytes32(uint256(3)),
            oracleJournalHash: bytes32(uint256(4)),
            fromSequence: 100,
            toSequence: 200,
            asOfTimestamp: 1700000000,
            netTraderPnLUSDC: -123,
            customerLiabilityUSDC: 456,
            reportedMaxOpenExposureUSDC: 789,
            reportedRequiredLPCapitalUSDC: 1000,
            realizedProfitHWMUSDC: 50,
            depositBatchHash: keccak256(abi.encode(ids)),
            deadline: 1800000000
        });
        assertEq(
            SettlementController(VECTOR_MODULE).hashSettlement(s),
            0x2e874bd4fadf19fea82be9b5d3de8c723522f85bae43b70184d69d965acf4532
        );
    }

    function testGoReserveAndRewardVectorsMatchActualContracts() public {
        vm.etch(VECTOR_MODULE, address(lp).code);
        LPVault.ReserveAuthorization memory r = LPVault.ReserveAuthorization({
            epoch: 7,
            checkpointRoot: bytes32(uint256(2)),
            amountUSDC: 123,
            minLPCapitalUSDC: 1000,
            realizedProfitHWMUSDC: 50,
            authorizationId: bytes32(uint256(4)),
            deadline: 1800000000
        });
        assertEq(
            LPVault(VECTOR_MODULE).hashReserveAuthorization(r),
            0xdc95bf3ec76d8cabaa4d63e6a79a0f34c2735a258df6828b1d66195e0c64d3ae
        );
        vm.etch(VECTOR_MODULE, address(rewards).code);
        assertEq(
            RewardDistributor(VECTOR_MODULE).rewardLeaf(7, 3, VECTOR_ACCOUNT, 123456789),
            0x4c384d1544934d3ea1a1e205ede5a00745c6195790e3e36980f3d90c59f1af4e
        );
    }

    function testGoLPCapacityAndUtilizationVectorsMatchActualContracts() public {
        vm.etch(VECTOR_MODULE, address(lp.shareVault()).code);
        LPShareVault.CapacityAuthorization memory a =
            LPShareVault.CapacityAuthorization(7, bytes32(uint256(2)), 123456789, 3, 1800000000);
        assertEq(
            LPShareVault(VECTOR_MODULE).hashCapacity(a),
            0x5400502bb741c2e7151fabe259ab6112e258badf23d15a413a79976d14d4b05e
        );
        LPIncentiveDistributor incentives = new LPIncentiveDistributor(access, token, lp.shareVault());
        vm.etch(VECTOR_MODULE, address(incentives).code);
        LPIncentiveDistributor.UtilizationReport memory r =
            LPIncentiveDistributor.UtilizationReport(7, 123456789, bytes32(uint256(3)), 1800000000);
        assertEq(
            LPIncentiveDistributor(VECTOR_MODULE).hashUtilization(r),
            0x229b2af9c0995ca5ca5606fe7c3e47251e4a00fc0a33fead2d6369b960cf1f3d
        );
    }
}
