// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC1271} from "@openzeppelin/contracts/interfaces/IERC1271.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {FUSEFixture} from "./helpers/FUSEFixture.sol";
import {AccessController} from "../src/AccessController.sol";
import {WithdrawalGateway} from "../src/WithdrawalGateway.sol";
import {ISettlementView} from "../src/interfaces/ISettlementView.sol";

contract MockSignerWallet is IERC1271 {
    address private immutable owner;

    constructor(address owner_) {
        owner = owner_;
    }

    function isValidSignature(bytes32 digest, bytes memory signature) external view returns (bytes4) {
        return ECDSA.recover(digest, signature) == owner ? IERC1271.isValidSignature.selector : bytes4(0);
    }
}

contract SignatureCompatibilityTest is FUSEFixture {
    function setUp() public {
        _deploy();
    }

    function testWithdrawalMatchesStandardTypedDataEncoding() public {
        _credit(100e6);
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        bytes32 structHash = vm.eip712HashStruct(
            "WithdrawalAuthorization(address account,address recipient,uint256 cumulativeAmountUSDC,uint64 stateVersion,uint64 validUntil,bytes32 authorizationId,bytes32 accountStateHash,uint256 signatureVersion)",
            abi.encode(
                a.account,
                a.recipient,
                a.cumulativeAmountUSDC,
                a.stateVersion,
                a.validUntil,
                a.authorizationId,
                a.accountStateHash,
                access.signatureVersion()
            )
        );
        assertEq(gateway.hashWithdrawal(a), _typedDigest("FUSE WithdrawalGateway", address(gateway), structHash));
    }

    function testSettlementMatchesStandardTypedDataEncoding() public view {
        bytes32 structHash = vm.eip712HashStruct(
            "EpochSettlement(uint64 epoch,bytes32 priorRoot,bytes32 newRoot,bytes32 journalHash,bytes32 oracleJournalHash,uint64 fromSequence,uint64 toSequence,uint64 asOfTimestamp,int256 netTraderPnLUSDC,uint256 customerLiabilityUSDC,uint256 reportedMaxOpenExposureUSDC,uint256 reportedRequiredLPCapitalUSDC,uint256 realizedProfitHWMUSDC,bytes32 depositBatchHash,uint256 deadline,uint256 signatureVersion)",
            abi.encode(_report(0, 0, new uint256[](0)), access.signatureVersion())
        );
        assertEq(
            controller.hashSettlement(_report(0, 0, new uint256[](0))),
            _typedDigest("FUSE SettlementController", address(controller), structHash)
        );
    }

    function _typedDigest(string memory name, address module, bytes32 structHash) private view returns (bytes32) {
        bytes32 domain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256(bytes(name)),
                keccak256("1"),
                block.chainid,
                module
            )
        );
        return keccak256(abi.encodePacked(hex"1901", domain, structHash));
    }

    function testContractSettlementRiskAndWithdrawalSigners() public {
        access.setSigner(access.SETTLEMENT_SIGNER(), address(new MockSignerWallet(vm.addr(SETTLEMENT_KEY))));
        access.setSigner(access.RISK_SIGNER(), address(new MockSignerWallet(vm.addr(RISK_KEY))));
        access.setSigner(access.WITHDRAWAL_SIGNER(), address(new MockSignerWallet(vm.addr(WITHDRAWAL_KEY))));
        _credit(100e6);
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        gateway.claim(a, _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(a)), "");
        assertEq(usdc.balanceOf(alice), 100e6);
    }

    function testContractAccountCanConsentToRelayedRedirect() public {
        _credit(100e6);
        address account = address(new MockSignerWallet(vm.addr(ALICE_KEY)));
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(account, bob, 100e6, bytes32(uint256(1)));
        bytes32 digest = gateway.hashWithdrawal(a);
        gateway.claim(a, _sign(WITHDRAWAL_KEY, digest), _sign(ALICE_KEY, digest));
        assertEq(usdc.balanceOf(bob), 100e6);
    }

    function testSameAuthorizationCannotReplayOnAnotherGateway() public {
        _credit(100e6);
        WithdrawalGateway second = new WithdrawalGateway(access, custody, ISettlementView(address(controller)));
        WithdrawalGateway.WithdrawalAuthorization memory a = _authorization(alice, alice, 100e6, bytes32(uint256(1)));
        bytes memory signature = _sign(WITHDRAWAL_KEY, gateway.hashWithdrawal(a));
        vm.expectRevert(AccessController.InvalidSignature.selector);
        second.claim(a, signature, "");
    }
}
