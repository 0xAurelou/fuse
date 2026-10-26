// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {Deploy} from "../script/Deploy.s.sol";
import {MockUSDC} from "./helpers/FUSEFixture.sol";
import {AccessController} from "../src/AccessController.sol";
import {Module} from "../src/common/Module.sol";

contract GovernanceDeploymentTest is Test {
    function testDeploymentBootstrapIsTimelockedAndStartsPaused() public {
        Deploy deployer = new Deploy();
        MockUSDC usdc = new MockUSDC();
        Deploy.Deployment memory d = deployer.deploy(usdc, address(this), 2 days, 1 days, 2 days);
        Deploy.Authorities memory a = Deploy.Authorities({
            settlement: address(0x11),
            risk: address(0x22),
            withdrawal: address(0x33),
            publisher: address(0x44),
            scheduler: address(0x55),
            guardian: address(0x66),
            lpProvider: address(0x77)
        });
        assertEq(d.access.governance(), address(d.timelock));
        bytes32 role = d.access.SETTLEMENT_SIGNER();
        vm.expectRevert(AccessController.Unauthorized.selector);
        d.access.setSigner(role, address(0x88));
        vm.expectRevert(Module.Unauthorized.selector);
        d.custody.configure(address(d.controller), address(d.gateway), address(d.lp));
        (address[] memory targets, uint256[] memory values, bytes[] memory payloads) = deployer.bootstrapBatch(d, a);
        bytes32 salt = keccak256("bootstrap");
        d.timelock.scheduleBatch(targets, values, payloads, bytes32(0), salt, 2 days);
        vm.expectRevert();
        d.timelock.executeBatch(targets, values, payloads, bytes32(0), salt);
        vm.warp(block.timestamp + 2 days);
        vm.prank(address(0xCA11));
        d.timelock.executeBatch(targets, values, payloads, bytes32(0), salt);
        assertTrue(d.access.tradingPaused());
        assertFalse(d.rewards.emissionsActive());
        assertFalse(d.reserve.redemptionsActive());
        assertFalse(d.token.transfersEnabled());
        assertEq(uint8(d.shares.phase()), 0);
        assertEq(d.lpRewards.start(), 0);
        assertEq(address(d.shares.incentives()), address(d.lpRewards));
        assertEq(d.token.lpEmissionEscrow().distributor(), address(d.lpRewards));
        assertEq(d.custody.settlementController(), address(d.controller));
        assertEq(d.lp.reserve(), address(d.reserve));
        assertFalse(d.timelock.hasRole(d.timelock.DEFAULT_ADMIN_ROLE(), address(this)));
        assertTrue(d.timelock.hasRole(d.timelock.DEFAULT_ADMIN_ROLE(), address(d.timelock)));
        vm.prank(a.guardian);
        vm.expectRevert(AccessController.Unauthorized.selector);
        d.access.resumeTrading();
        vm.prank(a.guardian);
        vm.expectRevert(Module.Unauthorized.selector);
        d.custody.payUser(a.guardian, 1, bytes32(uint256(1)));
    }
}
