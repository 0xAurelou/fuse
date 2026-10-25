// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {SignatureChecker} from "@openzeppelin/contracts/utils/cryptography/SignatureChecker.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {CustomerCustodyVault} from "./CustomerCustodyVault.sol";
import {ISettlementView} from "./interfaces/ISettlementView.sol";

contract WithdrawalGateway is Module, EIP712, ReentrancyGuard {
    struct WithdrawalAuthorization {
        address account;
        address recipient;
        uint256 cumulativeAmountUSDC;
        uint64 stateVersion;
        uint64 validUntil;
        bytes32 authorizationId;
        bytes32 accountStateHash;
    }
    bytes32 public constant WITHDRAWAL_TYPEHASH = keccak256(
        "WithdrawalAuthorization(address account,address recipient,uint256 cumulativeAmountUSDC,uint64 stateVersion,uint64 validUntil,bytes32 authorizationId,bytes32 accountStateHash,uint256 signatureVersion)"
    );
    CustomerCustodyVault public immutable custody;
    ISettlementView public immutable settlementController;
    mapping(address => uint256) public withdrawnCumulative;
    mapping(bytes32 => bool) public usedAuthorizations;
    error InvalidAuthorization();
    error RecipientNotAuthorized();
    event Withdrawn(
        address indexed account, address indexed recipient, bytes32 indexed authorizationId, uint256 amount
    );

    constructor(AccessController access_, CustomerCustodyVault custody_, ISettlementView controller)
        Module(access_)
        EIP712("FUSE WithdrawalGateway", "1")
    {
        if (address(custody_) == address(0) || address(controller) == address(0)) {
            revert InvalidConfiguration();
        }
        custody = custody_;
        settlementController = controller;
    }

    function hashWithdrawal(WithdrawalAuthorization calldata authorization) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(WITHDRAWAL_TYPEHASH, authorization, access.signatureVersion())));
    }

    /// @param recipientConsent Account signature over the same typed authorization for relayed redirects.
    /// Direct account submissions also independently authorize their recipient.
    function claim(
        WithdrawalAuthorization calldata authorization,
        bytes calldata operatorSignature,
        bytes calldata recipientConsent
    ) external nonReentrant returns (uint256 amount) {
        if (
            authorization.account == address(0) || authorization.recipient == address(0)
                || authorization.validUntil < block.timestamp || authorization.stateVersion == 0
                || authorization.stateVersion > settlementController.latestEpoch()
                || authorization.authorizationId == bytes32(0) || authorization.accountStateHash == bytes32(0)
                || usedAuthorizations[authorization.authorizationId]
                || authorization.cumulativeAmountUSDC <= withdrawnCumulative[authorization.account]
        ) revert InvalidAuthorization();
        bytes32 digest = hashWithdrawal(authorization);
        access.verify(access.WITHDRAWAL_SIGNER(), digest, operatorSignature);
        if (
            authorization.recipient != authorization.account && msg.sender != authorization.account
                && !SignatureChecker.isValidSignatureNow(authorization.account, digest, recipientConsent)
        ) revert RecipientNotAuthorized();
        amount = authorization.cumulativeAmountUSDC - withdrawnCumulative[authorization.account];
        withdrawnCumulative[authorization.account] = authorization.cumulativeAmountUSDC;
        usedAuthorizations[authorization.authorizationId] = true;
        custody.payUser(authorization.recipient, amount, authorization.authorizationId);
        emit Withdrawn(authorization.account, authorization.recipient, authorization.authorizationId, amount);
    }
}
