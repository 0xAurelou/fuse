#!/usr/bin/env python3
"""Exact rational release-model vectors for the real share-vault integration."""
import argparse
from pathlib import Path
from release_lp_bootstrap import DAY, USDC, Segment, epoch_entitlements


def vectors():
    protocol = 1_000_000*USDC
    alice = 100_000*USDC
    def segment(seconds, bob=0, eligible=True):
        equity = {'protocol':protocol, 'alice':alice}
        if bob:
            equity['bob'] = bob*USDC
        owners = frozenset({'alice'} | ({'bob'} if bob else set())) if eligible else frozenset()
        return Segment(seconds,equity,owners,sum(equity.values())//5)
    return [
        epoch_entitlements(0,[segment(DAY)]),
        epoch_entitlements(0,[segment(DAY//2),segment(DAY//2,1_900_000)]),
        epoch_entitlements(0,[segment(DAY//2),segment(DAY//2,eligible=False)]),
        epoch_entitlements(0,[segment(DAY//2),segment(DAY//2,500_000)]),
    ]


def render():
    rows = vectors()
    lines = ['// SPDX-License-Identifier: MIT','pragma solidity ^0.8.24;',
             '// Generated from exact Fraction capital-time; never from contract output.',
             'library LPBootstrapVectors {',
             '    function row(uint256 n) internal pure returns (uint256[4] memory) {']
    for i,row in enumerate(rows):
        values = [row['capital_usdc_seconds'],row['liability_usdc_seconds'],
                  row['entitlements'].get('alice',0),row['entitlements'].get('bob',0)]
        lines.append(f'        if (n == {i}) return [uint256('+str(values[0])+'), '+', '.join(map(str,values[1:]))+'];')
    lines += ['        revert("unknown bootstrap vector");','    }','}','']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.parse_args().output.write_text(render())
