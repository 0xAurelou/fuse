// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {FUSEToken} from "./FUSEToken.sol";
import {EmissionEscrow} from "./AllocationEscrows.sol";

contract RewardDistributor is Module, ReentrancyGuard {
    struct RewardEpoch {
        bytes32 merkleRoot;
        bytes32 manifestHash;
        uint256 budget;
        uint256 claimed;
    }
    FUSEToken public immutable token;
    EmissionEscrow public immutable escrow;
    mapping(uint64 => RewardEpoch) public epochs;
    mapping(uint64 => mapping(uint256 => uint256)) private claimedBitmap;
    uint64 public latestEpoch;
    uint64 public emissionStart;
    uint64 public epochDuration;
    uint16 public decayBps;
    uint256 public nextEpochCap;
    uint256 public totalAllocated;
    uint256 public totalClaimed;
    bool public emissionsActive;
    error InvalidEpoch();
    error InvalidClaim();
    event EmissionScheduleConfigured(uint64 start, uint64 duration, uint256 initialBudget, uint16 decayBps);
    event EmissionsActivated();
    event EpochPublished(uint64 indexed epoch, bytes32 merkleRoot, uint256 budget, bytes32 manifestHash);
    event RewardClaimed(uint64 indexed epoch, uint256 indexed index, address indexed recipient, uint256 amount);

    constructor(AccessController access_, FUSEToken token_) Module(access_) {
        if (address(token_) == address(0)) revert InvalidConfiguration();
        token = token_;
        escrow = token_.emissionEscrow();
    }

    /// @notice A configurable discrete decay, rather than the unapproved 20-day half-life.
    function configureEmissionSchedule(uint64 start, uint64 duration, uint256 initialBudget, uint16 decay)
        external
        onlyGovernance
    {
        if (
            emissionStart != 0 || start < block.timestamp || start == 0 || duration == 0 || initialBudget == 0
                || initialBudget > token.EMISSION_ALLOCATION() || decay == 0 || decay >= 10_000
        ) revert InvalidConfiguration();
        emissionStart = start;
        epochDuration = duration;
        nextEpochCap = initialBudget;
        decayBps = decay;
        emit EmissionScheduleConfigured(start, duration, initialBudget, decay);
    }

    function activateEmissions() external onlyGovernance {
        if (emissionStart == 0 || escrow.distributor() != address(this) || emissionsActive) {
            revert InvalidConfiguration();
        }
        emissionsActive = true;
        emit EmissionsActivated();
    }

    function publishEpoch(uint64 epoch, bytes32 merkleRoot, uint256 budget, bytes32 manifestHash)
        external
        onlyRole(access.EMISSION_PUBLISHER())
        whenTradingActive
    {
        if (
            !emissionsActive || epoch != latestEpoch + 1 || merkleRoot == bytes32(0) || manifestHash == bytes32(0)
                || budget == 0 || budget > nextEpochCap || totalAllocated + budget > token.EMISSION_ALLOCATION()
                || block.timestamp < uint256(emissionStart) + uint256(epoch - 1) * epochDuration
        ) revert InvalidEpoch();
        latestEpoch = epoch;
        totalAllocated += budget;
        epochs[epoch] = RewardEpoch(merkleRoot, manifestHash, budget, 0);
        nextEpochCap = Math.mulDiv(nextEpochCap, 10_000 - decayBps, 10_000);
        emit EpochPublished(epoch, merkleRoot, budget, manifestHash);
    }

    /// @dev OpenZeppelin StandardMerkleTree compatible leaf, bound to chain and distributor.
    function rewardLeaf(uint64 epoch, uint256 index, address recipient, uint256 amount) public view returns (bytes32) {
        return
            keccak256(
                bytes.concat(keccak256(abi.encode(block.chainid, address(this), epoch, index, recipient, amount)))
            );
    }

    function isClaimed(uint64 epoch, uint256 index) public view returns (bool) {
        return claimedBitmap[epoch][index >> 8] & (uint256(1) << (index & 255)) != 0;
    }

    function claim(uint64 epoch, uint256 index, address recipient, uint256 amount, bytes32[] calldata proof)
        external
        nonReentrant
    {
        RewardEpoch storage rewardEpoch = epochs[epoch];
        if (
            recipient == address(0) || amount == 0 || isClaimed(epoch, index) || rewardEpoch.merkleRoot == bytes32(0)
                || rewardEpoch.claimed + amount > rewardEpoch.budget
                || !MerkleProof.verifyCalldata(
                    proof, rewardEpoch.merkleRoot, rewardLeaf(epoch, index, recipient, amount)
                )
        ) {
            revert InvalidClaim();
        }
        claimedBitmap[epoch][index >> 8] |= uint256(1) << (index & 255);
        rewardEpoch.claimed += amount;
        totalClaimed += amount;
        escrow.release(recipient, amount);
        emit RewardClaimed(epoch, index, recipient, amount);
    }
}
