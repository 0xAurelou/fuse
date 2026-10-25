// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ISettlementView {
    function latestEpoch() external view returns (uint64);
    function currentRoot() external view returns (bytes32);
}
