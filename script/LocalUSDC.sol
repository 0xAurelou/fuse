// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @notice Faucet asset for the local Anvil integration only.
contract LocalUSDC is ERC20 {
    constructor() ERC20("Local Test USDC", "USDC") {
        require(block.chainid == 31337, "LOCAL_CHAIN_ONLY");
    }

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address recipient, uint256 amount) external {
        require(block.chainid == 31337, "LOCAL_CHAIN_ONLY");
        _mint(recipient, amount);
    }
}
