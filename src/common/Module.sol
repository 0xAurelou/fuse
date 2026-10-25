// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessController} from "../AccessController.sol";

abstract contract Module {
    AccessController public immutable access;
    error Unauthorized();
    error InvalidConfiguration();
    error TradingPaused();

    constructor(AccessController access_) {
        if (address(access_) == address(0)) revert InvalidConfiguration();
        access = access_;
    }

    modifier onlyGovernance() {
        if (msg.sender != access.governance()) revert Unauthorized();
        _;
    }

    modifier onlyRole(bytes32 role) {
        if (!access.hasRole(role, msg.sender)) revert Unauthorized();
        _;
    }

    modifier whenTradingActive() {
        if (access.tradingPaused()) revert TradingPaused();
        _;
    }
}
