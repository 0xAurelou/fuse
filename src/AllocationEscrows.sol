// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";

contract EmissionEscrow is Module {
    using SafeERC20 for IERC20;
    IERC20 public immutable token;
    address public distributor;

    constructor(AccessController access_, IERC20 token_) Module(access_) {
        token = token_;
    }

    function setDistributor(address distributor_) external onlyGovernance {
        if (distributor != address(0) || distributor_.code.length == 0) revert InvalidConfiguration();
        distributor = distributor_;
    }

    function release(address recipient, uint256 amount) external {
        if (msg.sender != distributor) revert Unauthorized();
        token.safeTransfer(recipient, amount);
    }
}

/// @notice Locked until timelocked governance approves a separate immutable allocation manifest.
/// Claims also obey the token's transfer activation gate; no discretionary release/rescue exists.
contract TreasuryEscrow is Module, ReentrancyGuard {
    using SafeERC20 for IERC20;
    IERC20 public immutable token;
    uint256 public constant ALLOCATION = 350_000_000 ether;
    bytes32 public allocationRoot;
    bytes32 public manifestHash;
    uint256 public totalReleased;
    mapping(uint256 => uint256) private claimedBitmap;

    error InvalidPolicy();
    error InvalidClaim();
    event AllocationPolicyApproved(bytes32 indexed root, bytes32 indexed manifestHash);
    event AllocationClaimed(uint256 indexed index, address indexed recipient, uint256 amount);

    constructor(AccessController access_, IERC20 token_) Module(access_) {
        token = token_;
    }

    function approveAllocationPolicy(bytes32 root, bytes32 manifestHash_) external onlyGovernance {
        if (allocationRoot != bytes32(0) || root == bytes32(0) || manifestHash_ == bytes32(0)) revert InvalidPolicy();
        allocationRoot = root;
        manifestHash = manifestHash_;
        emit AllocationPolicyApproved(root, manifestHash_);
    }

    function allocationLeaf(uint256 index, address recipient, uint256 amount) public view returns (bytes32) {
        return keccak256(bytes.concat(keccak256(abi.encode(block.chainid, address(this), index, recipient, amount))));
    }

    function isClaimed(uint256 index) public view returns (bool) {
        return claimedBitmap[index >> 8] & (uint256(1) << (index & 255)) != 0;
    }

    function claim(uint256 index, address recipient, uint256 amount, bytes32[] calldata proof) external nonReentrant {
        if (
            allocationRoot == bytes32(0) || recipient == address(0) || amount == 0 || isClaimed(index)
                || totalReleased + amount > ALLOCATION
                || !MerkleProof.verifyCalldata(proof, allocationRoot, allocationLeaf(index, recipient, amount))
        ) revert InvalidClaim();
        claimedBitmap[index >> 8] |= uint256(1) << (index & 255);
        totalReleased += amount;
        token.safeTransfer(recipient, amount);
        emit AllocationClaimed(index, recipient, amount);
    }
}
