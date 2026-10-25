// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {AccessController} from "../src/AccessController.sol";
import {CustomerCustodyVault} from "../src/CustomerCustodyVault.sol";
import {LPVault} from "../src/LPVault.sol";
import {SettlementController} from "../src/SettlementController.sol";
import {WithdrawalGateway} from "../src/WithdrawalGateway.sol";
import {FUSEToken} from "../src/FUSEToken.sol";
import {RewardDistributor} from "../src/RewardDistributor.sol";
import {RedemptionReserve} from "../src/RedemptionReserve.sol";
import {ISettlementView} from "../src/interfaces/ISettlementView.sol";

/// @notice Deploys unconfigured modules and emits the exact timelock bootstrap batch.
/// Does not activate mining, redemption or token transfers. Never broadcasts implicitly.
contract Deploy is Script {
    struct Deployment {
        TimelockController timelock;
        AccessController access;
        CustomerCustodyVault custody;
        LPVault lp;
        SettlementController controller;
        WithdrawalGateway gateway;
        FUSEToken token;
        RewardDistributor rewards;
        RedemptionReserve reserve;
    }

    struct Authorities {
        address settlement;
        address risk;
        address withdrawal;
        address publisher;
        address scheduler;
        address guardian;
        address lpProvider;
    }

    event ModulesDeployed(
        address timelock,
        address accessController,
        address custody,
        address lpVault,
        address settlementController,
        address withdrawalGateway,
        address token,
        address rewards,
        address reserve
    );
    event BootstrapBatch(
        address[] targets, uint256[] values, bytes[] payloads, bytes32 predecessor, bytes32 salt, uint256 delay
    );

    function run() external returns (Deployment memory deployment) {
        require(block.chainid == 998 || block.chainid == 999 || block.chainid == 31337, "unsupported chain");
        IERC20 usdc = IERC20(vm.envAddress("USDC_ADDRESS"));
        address multisig = vm.envAddress("GOVERNANCE_MULTISIG");
        uint256 governanceDelay = vm.envUint("GOVERNANCE_DELAY");
        uint256 refundTimeout = vm.envUint("DEPOSIT_REFUND_TIMEOUT");
        uint256 transferDelay = vm.envUint("TRANSFER_ACTIVATION_DELAY");
        require(
            address(usdc).code.length != 0 && multisig != address(0) && governanceDelay != 0, "invalid governance/asset"
        );
        if (block.chainid != 31337) require(multisig.code.length != 0, "governance must be a multisig contract");
        Authorities memory authorities = Authorities({
            settlement: vm.envAddress("SETTLEMENT_SIGNER"),
            risk: vm.envAddress("RISK_SIGNER"),
            withdrawal: vm.envAddress("WITHDRAWAL_SIGNER"),
            publisher: vm.envAddress("EMISSION_PUBLISHER"),
            scheduler: vm.envAddress("REDEMPTION_SCHEDULER"),
            guardian: vm.envAddress("GUARDIAN"),
            lpProvider: vm.envAddress("LP_PROVIDER")
        });
        vm.startBroadcast();
        deployment = deploy(usdc, multisig, governanceDelay, refundTimeout, transferDelay);
        vm.stopBroadcast();
        emit ModulesDeployed(
            address(deployment.timelock),
            address(deployment.access),
            address(deployment.custody),
            address(deployment.lp),
            address(deployment.controller),
            address(deployment.gateway),
            address(deployment.token),
            address(deployment.rewards),
            address(deployment.reserve)
        );
        (address[] memory targets, uint256[] memory values, bytes[] memory payloads) =
            bootstrapBatch(deployment, authorities);
        emit BootstrapBatch(targets, values, payloads, bytes32(0), keccak256("FUSE_V0_BOOTSTRAP"), governanceDelay);
    }

    /// @dev Public helpers also allow a local integration test without environment/private keys.
    function deploy(IERC20 usdc, address multisig, uint256 delay, uint256 refundTimeout, uint256 transferDelay)
        public
        returns (Deployment memory d)
    {
        require(address(usdc).code.length != 0 && multisig != address(0) && delay != 0, "invalid deployment");
        address[] memory proposers = new address[](1);
        proposers[0] = multisig;
        address[] memory executors = new address[](1);
        executors[0] = address(0); // Anyone may execute, only after a multisig proposal and the delay.
        d.timelock = new TimelockController(delay, proposers, executors, address(0));
        d.access = new AccessController(address(d.timelock));
        d.custody = new CustomerCustodyVault(d.access, usdc, refundTimeout);
        d.lp = new LPVault(d.access, usdc);
        d.controller = new SettlementController(d.access, d.custody, d.lp);
        d.gateway = new WithdrawalGateway(d.access, d.custody, ISettlementView(address(d.controller)));
        d.token = new FUSEToken(d.access, transferDelay);
        d.rewards = new RewardDistributor(d.access, d.token);
        d.reserve = new RedemptionReserve(d.access, usdc, d.token, address(d.lp));
    }

    function bootstrapBatch(Deployment memory d, Authorities memory a)
        public
        view
        returns (address[] memory targets, uint256[] memory values, bytes[] memory payloads)
    {
        require(
            a.settlement != address(0) && a.risk != address(0) && a.settlement != a.risk && a.withdrawal != address(0)
                && a.publisher != address(0) && a.scheduler != address(0) && a.guardian != address(0)
                && a.lpProvider != address(0),
            "invalid authorities"
        );
        targets = new address[](14);
        values = new uint256[](14);
        payloads = new bytes[](14);
        targets[0] = address(d.custody);
        payloads[0] = abi.encodeCall(d.custody.configure, (address(d.controller), address(d.gateway), address(d.lp)));
        targets[1] = address(d.lp);
        payloads[1] = abi.encodeCall(
            d.lp.configure, (address(d.custody), ISettlementView(address(d.controller)), address(d.reserve))
        );
        targets[2] = address(d.token);
        payloads[2] = abi.encodeCall(d.token.setRedemptionReserve, (address(d.reserve)));
        targets[3] = address(d.token.emissionEscrow());
        payloads[3] = abi.encodeCall(d.token.emissionEscrow().setDistributor, (address(d.rewards)));
        for (uint256 i = 4; i < 14; ++i) {
            targets[i] = address(d.access);
        }
        payloads[4] = abi.encodeCall(d.access.setSigner, (d.access.SETTLEMENT_SIGNER(), a.settlement));
        payloads[5] = abi.encodeCall(d.access.setSigner, (d.access.RISK_SIGNER(), a.risk));
        payloads[6] = abi.encodeCall(d.access.setSigner, (d.access.WITHDRAWAL_SIGNER(), a.withdrawal));
        payloads[7] = abi.encodeCall(d.access.grantRole, (d.access.EMISSION_PUBLISHER(), a.publisher));
        payloads[8] = abi.encodeCall(d.access.grantRole, (d.access.REDEMPTION_SCHEDULER(), a.scheduler));
        payloads[9] = abi.encodeCall(d.access.grantRole, (d.access.LP_PROVIDER(), a.lpProvider));
        payloads[10] = abi.encodeCall(d.access.grantRole, (d.access.GUARDIAN(), a.guardian));
        // Bootstrap atomically into a paused state. Only a subsequent timelocked action may resume.
        payloads[11] = abi.encodeCall(d.access.grantRole, (d.access.GUARDIAN(), address(d.timelock)));
        payloads[12] = abi.encodeCall(d.access.pauseTrading, ());
        payloads[13] = abi.encodeCall(d.access.revokeRole, (d.access.GUARDIAN(), address(d.timelock)));
    }
}
