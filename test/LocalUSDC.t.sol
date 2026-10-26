// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {LocalUSDC} from "../script/LocalUSDC.sol";

contract LocalUSDCTest is Test {
    function testLocalFaucetUsesUSDCUnits() public {
        vm.chainId(31337);
        LocalUSDC asset = new LocalUSDC();
        asset.mint(address(0xA11CE), 100e6);
        assertEq(asset.decimals(), 6);
        assertEq(asset.balanceOf(address(0xA11CE)), 100e6);
    }

    function testFaucetDeploymentRefusesPublicChain() public {
        vm.chainId(999);
        vm.expectRevert("LOCAL_CHAIN_ONLY");
        new LocalUSDC();
    }

    function testFaucetMintRefusesChangedChain() public {
        vm.chainId(31337);
        LocalUSDC asset = new LocalUSDC();
        vm.chainId(999);
        vm.expectRevert("LOCAL_CHAIN_ONLY");
        asset.mint(address(0xA11CE), 100e6);
    }
}
