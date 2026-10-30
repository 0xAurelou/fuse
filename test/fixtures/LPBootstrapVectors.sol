// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
// Generated from exact Fraction capital-time; never from contract output.
library LPBootstrapVectors {
    function row(uint256 n) internal pure returns (uint256[4] memory) {
        if (n == 0) return [uint256(95040000000000000), 19008000000000000, 69401081522293643505764, 0];
        if (n == 1) return [uint256(177120000000000000), 35424000000000000, 18619802359639758013741, 0];
        if (n == 2) return [uint256(95040000000000000), 19008000000000000, 34700540761146821752882, 0];
        if (n == 3) return [uint256(116640000000000000), 23328000000000000, 49108367626886145404663, 104169264663091823585650];
        revert("unknown bootstrap vector");
    }
}
