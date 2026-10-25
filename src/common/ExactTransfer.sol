// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @dev Checks both endpoints. Unsupported taxed/rebasing assets fail atomically.
library ExactTransfer {
    using SafeERC20 for IERC20;
    error UnexpectedTransfer();

    function pull(IERC20 token, address from, uint256 amount) internal {
        uint256 beforeFrom = token.balanceOf(from);
        uint256 beforeTo = token.balanceOf(address(this));
        token.safeTransferFrom(from, address(this), amount);
        if (token.balanceOf(from) != beforeFrom - amount || token.balanceOf(address(this)) != beforeTo + amount) {
            revert UnexpectedTransfer();
        }
    }

    function push(IERC20 token, address to, uint256 amount) internal {
        if (to == address(this) || to == address(0)) revert UnexpectedTransfer();
        uint256 beforeFrom = token.balanceOf(address(this));
        uint256 beforeTo = token.balanceOf(to);
        token.safeTransfer(to, amount);
        if (token.balanceOf(address(this)) != beforeFrom - amount || token.balanceOf(to) != beforeTo + amount) {
            revert UnexpectedTransfer();
        }
    }
}
