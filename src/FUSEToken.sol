// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {AccessController} from "./AccessController.sol";
import {Module} from "./common/Module.sol";
import {EmissionEscrow, TreasuryEscrow} from "./AllocationEscrows.sol";

contract FUSEToken is ERC20, Module {
    uint256 public constant GENESIS_SUPPLY = 1_000_000_000 ether;
    uint256 public constant EMISSION_ALLOCATION = 600_000_000 ether;
    uint256 public constant TREASURY_ALLOCATION = 400_000_000 ether;
    EmissionEscrow public immutable emissionEscrow;
    TreasuryEscrow public immutable treasuryEscrow;
    uint256 public immutable transferActivationDelay;
    address public redemptionReserve;
    uint256 public transfersEnableAfter;
    bool public transfersEnabled;

    error TransfersDisabled();
    error ActivationNotReady();
    event TransferActivationScheduled(uint256 enableAfter);
    event TransfersEnabled();
    event RedemptionReserveConfigured(address indexed reserve);

    constructor(AccessController access_, uint256 transferActivationDelay_) ERC20("FUSE", "FUSE") Module(access_) {
        if (transferActivationDelay_ == 0) revert InvalidConfiguration();
        transferActivationDelay = transferActivationDelay_;
        emissionEscrow = new EmissionEscrow(access_, IERC20(address(this)));
        treasuryEscrow = new TreasuryEscrow(access_, IERC20(address(this)));
        _mint(address(emissionEscrow), EMISSION_ALLOCATION);
        _mint(address(treasuryEscrow), TREASURY_ALLOCATION);
    }

    function setRedemptionReserve(address reserve) external onlyGovernance {
        if (redemptionReserve != address(0) || reserve.code.length == 0) revert InvalidConfiguration();
        redemptionReserve = reserve;
        emit RedemptionReserveConfigured(reserve);
    }

    function scheduleEnableTransfers() external onlyGovernance {
        if (transfersEnabled || transfersEnableAfter != 0) revert ActivationNotReady();
        transfersEnableAfter = block.timestamp + transferActivationDelay;
        emit TransferActivationScheduled(transfersEnableAfter);
    }

    function enableTransfers() external {
        if (transfersEnabled || transfersEnableAfter == 0 || block.timestamp < transfersEnableAfter) {
            revert ActivationNotReady();
        }
        transfersEnabled = true;
        emit TransfersEnabled();
    }

    function burnForRedemption(address account, uint256 amount) external {
        if (msg.sender != redemptionReserve) revert Unauthorized();
        _spendAllowance(account, msg.sender, amount);
        _burn(account, amount);
    }

    function _update(address from, address to, uint256 amount) internal override {
        if (from != address(0) && to != address(0) && from != address(emissionEscrow) && !transfersEnabled) {
            revert TransfersDisabled();
        }
        super._update(from, to, amount);
    }
}
