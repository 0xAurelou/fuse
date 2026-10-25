// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {CustomerCustodyVault} from "./CustomerCustodyVault.sol";
import {LPVault} from "./LPVault.sol";

/// @notice Attests operator accounting; it does not verify offchain outcomes or oracle prices.
contract SettlementController is Module, EIP712, ReentrancyGuard {
    struct EpochSettlement {
        uint64 epoch;
        bytes32 priorRoot;
        bytes32 newRoot;
        bytes32 journalHash;
        bytes32 oracleJournalHash;
        uint64 fromSequence;
        uint64 toSequence;
        uint64 asOfTimestamp;
        int256 netTraderPnLUSDC;
        uint256 customerLiabilityUSDC;
        uint256 reportedMaxOpenExposureUSDC;
        uint256 reportedRequiredLPCapitalUSDC;
        uint256 realizedProfitHWMUSDC;
        bytes32 depositBatchHash;
        uint256 deadline;
    }
    bytes32 public constant SETTLEMENT_TYPEHASH = keccak256(
        "EpochSettlement(uint64 epoch,bytes32 priorRoot,bytes32 newRoot,bytes32 journalHash,bytes32 oracleJournalHash,uint64 fromSequence,uint64 toSequence,uint64 asOfTimestamp,int256 netTraderPnLUSDC,uint256 customerLiabilityUSDC,uint256 reportedMaxOpenExposureUSDC,uint256 reportedRequiredLPCapitalUSDC,uint256 realizedProfitHWMUSDC,bytes32 depositBatchHash,uint256 deadline,uint256 signatureVersion)"
    );

    CustomerCustodyVault public immutable custody;
    LPVault public immutable lpVault;
    uint64 public latestEpoch;
    uint64 public lastSequence;
    uint64 public lastAsOfTimestamp;
    bytes32 public currentRoot;
    mapping(uint64 => bytes32) public checkpointHash;

    error InvalidCheckpoint();
    event CheckpointFinalized(
        uint64 indexed epoch,
        bytes32 indexed newRoot,
        bytes32 indexed digest,
        bytes32 journalHash,
        bytes32 oracleJournalHash,
        int256 netTraderPnLUSDC,
        uint256 customerLiabilityUSDC
    );

    constructor(AccessController access_, CustomerCustodyVault custody_, LPVault lpVault_)
        Module(access_)
        EIP712("FUSE SettlementController", "1")
    {
        if (address(custody_) == address(0) || address(lpVault_) == address(0) || custody_.usdc() != lpVault_.usdc()) {
            revert InvalidConfiguration();
        }
        custody = custody_;
        lpVault = lpVault_;
    }

    function hashSettlement(EpochSettlement calldata report) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(SETTLEMENT_TYPEHASH, report, access.signatureVersion())));
    }

    function settle(
        EpochSettlement calldata report,
        uint256[] calldata depositIds,
        bytes calldata settlementSignature,
        bytes calldata riskSignature
    ) external nonReentrant whenTradingActive {
        if (
            report.epoch != latestEpoch + 1 || report.priorRoot != currentRoot || report.newRoot == bytes32(0)
                || report.newRoot == currentRoot || report.journalHash == bytes32(0)
                || report.oracleJournalHash == bytes32(0) || report.fromSequence != lastSequence + 1
                || report.toSequence < report.fromSequence || report.asOfTimestamp < lastAsOfTimestamp
                || report.asOfTimestamp > block.timestamp || report.deadline < block.timestamp
                || report.depositBatchHash != keccak256(abi.encode(depositIds))
                || report.reportedRequiredLPCapitalUSDC < report.reportedMaxOpenExposureUSDC
                || report.netTraderPnLUSDC == type(int256).min
        ) revert InvalidCheckpoint();
        bytes32 digest = hashSettlement(report);
        access.verify(access.SETTLEMENT_SIGNER(), digest, settlementSignature);
        access.verify(access.RISK_SIGNER(), digest, riskSignature);
        custody.acknowledgeDeposits(depositIds, report.epoch);
        if (report.netTraderPnLUSDC > 0) {
            lpVault.fundNetTraderWins(report.epoch, uint256(report.netTraderPnLUSDC));
        } else if (report.netTraderPnLUSDC < 0) {
            uint256 amount = uint256(-report.netTraderPnLUSDC);
            custody.transferRealizedLossToLP(amount, report.epoch);
            lpVault.receiveNetTraderLosses(report.epoch, amount);
        }
        custody.finalizeLiability(report.customerLiabilityUSDC);
        lpVault.finalizeCapital(report.reportedRequiredLPCapitalUSDC, report.realizedProfitHWMUSDC);
        latestEpoch = report.epoch;
        lastSequence = report.toSequence;
        lastAsOfTimestamp = report.asOfTimestamp;
        currentRoot = report.newRoot;
        checkpointHash[report.epoch] = digest;
        emit CheckpointFinalized(
            report.epoch,
            report.newRoot,
            digest,
            report.journalHash,
            report.oracleJournalHash,
            report.netTraderPnLUSDC,
            report.customerLiabilityUSDC
        );
    }
}
