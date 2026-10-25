// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {SignatureChecker} from "@openzeppelin/contracts/utils/cryptography/SignatureChecker.sol";

/// @notice Governance must be a self-administered timelock controlled by a multisig.
/// Modules are immutable; governance cannot replace custody counterparties after wiring.
contract AccessController is AccessControl {
    bytes32 public constant SETTLEMENT_SIGNER = keccak256("SETTLEMENT_SIGNER");
    bytes32 public constant RISK_SIGNER = keccak256("RISK_SIGNER");
    bytes32 public constant WITHDRAWAL_SIGNER = keccak256("WITHDRAWAL_SIGNER");
    bytes32 public constant EMISSION_PUBLISHER = keccak256("EMISSION_PUBLISHER");
    bytes32 public constant REDEMPTION_SCHEDULER = keccak256("REDEMPTION_SCHEDULER");
    bytes32 public constant LP_PROVIDER = keccak256("LP_PROVIDER");
    bytes32 public constant GUARDIAN = keccak256("GUARDIAN");

    address public immutable governance;
    mapping(bytes32 => address) public signer;
    uint256 public signatureVersion = 1;
    bool public tradingPaused;

    error InvalidAuthority();
    error InvalidSignature();
    error Unauthorized();
    event SignerRotated(bytes32 indexed role, address indexed authority, uint256 signatureVersion);
    event TradingPauseChanged(bool paused);

    constructor(address governance_) {
        if (governance_ == address(0)) revert InvalidAuthority();
        governance = governance_;
        _grantRole(DEFAULT_ADMIN_ROLE, governance_);
    }

    function setSigner(bytes32 role, address authority) external {
        if (msg.sender != governance) revert Unauthorized();
        if (
            authority == address(0) || (role != SETTLEMENT_SIGNER && role != RISK_SIGNER && role != WITHDRAWAL_SIGNER)
                || (role == SETTLEMENT_SIGNER && authority == signer[RISK_SIGNER])
                || (role == RISK_SIGNER && authority == signer[SETTLEMENT_SIGNER])
        ) revert InvalidAuthority();
        signer[role] = authority;
        ++signatureVersion;
        emit SignerRotated(role, authority, signatureVersion);
    }

    function verify(bytes32 role, bytes32 digest, bytes calldata signature) external view {
        address authority = signer[role];
        if (authority == address(0) || !SignatureChecker.isValidSignatureNow(authority, digest, signature)) {
            revert InvalidSignature();
        }
    }

    /// @notice A guardian can stop new activity, never funded withdrawals or refunds.
    function pauseTrading() external onlyRole(GUARDIAN) {
        tradingPaused = true;
        emit TradingPauseChanged(true);
    }

    function resumeTrading() external {
        if (msg.sender != governance) revert Unauthorized();
        tradingPaused = false;
        emit TradingPauseChanged(false);
    }
}
