import subprocess,json

def cast(*args):
 return subprocess.check_output(['cast',*args],text=True).strip()
def kh(s):return cast('keccak',s)
def enc(types,*vals):return cast('abi-encode',f'f({types})',*map(str,vals))
def hstruct(schema,types,vals):return kh(enc('bytes32,'+types,kh(schema),*vals))
chain=998
contract='0x1111111111111111111111111111111111111111'
a='0x2222222222222222222222222222222222222222'
b='0x3333333333333333333333333333333333333333'
h=lambda n:'0x'+f'{n:064x}'
def digest(name,struct):
 domain=kh(enc('bytes32,bytes32,bytes32,uint256,address',kh('EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)'),kh(name),kh('1'),chain,contract))
 return kh('0x1901'+domain[2:]+struct[2:])
w=hstruct('WithdrawalAuthorization(address account,address recipient,uint256 cumulativeAmountUSDC,uint64 stateVersion,uint64 validUntil,bytes32 authorizationId,bytes32 accountStateHash,uint256 signatureVersion)', 'address,address,uint256,uint64,uint64,bytes32,bytes32,uint256',[a,b,123456789,7,1800000000,h(4),h(5),9])
deposit=kh(enc('uint256[]','[1,2,300]'))
s=hstruct('EpochSettlement(uint64 epoch,bytes32 priorRoot,bytes32 newRoot,bytes32 journalHash,bytes32 oracleJournalHash,uint64 fromSequence,uint64 toSequence,uint64 asOfTimestamp,int256 netTraderPnLUSDC,uint256 customerLiabilityUSDC,uint256 reportedMaxOpenExposureUSDC,uint256 reportedRequiredLPCapitalUSDC,uint256 realizedProfitHWMUSDC,bytes32 depositBatchHash,uint256 deadline,uint256 signatureVersion)','uint64,bytes32,bytes32,bytes32,bytes32,uint64,uint64,uint64,int256,uint256,uint256,uint256,uint256,bytes32,uint256,uint256',[7,h(1),h(2),h(3),h(4),100,200,1700000000,-123,456,789,1000,50,deposit,1800000000,9])
r=hstruct('ReserveAuthorization(uint64 epoch,bytes32 checkpointRoot,uint256 amountUSDC,uint256 minLPCapitalUSDC,uint256 realizedProfitHWMUSDC,bytes32 authorizationId,uint256 deadline,uint256 signatureVersion)','uint64,bytes32,uint256,uint256,uint256,bytes32,uint256,uint256',[7,h(2),123,1000,50,h(4),1800000000,9])
leaf=kh(kh(enc('uint256,address,uint64,uint256,address,uint256',chain,contract,7,3,a,123456789)))
lp_capacity=hstruct('CapacityAuthorization(uint64 epoch,bytes32 checkpointRoot,uint256 eligibleDemandUSDC,uint256 nonce,uint256 deadline,uint256 signatureVersion)','uint64,bytes32,uint256,uint256,uint256,uint256',[7,h(2),123456789,3,1800000000,9])
lp_utilization=hstruct('LPUtilizationReport(uint64 epoch,uint256 liabilitySeconds,bytes32 journalHash,uint256 deadline,uint256 signatureVersion)','uint64,uint256,bytes32,uint256,uint256',[7,123456789,h(3),1800000000,9])
print(json.dumps(dict(chain=chain,contract=contract,account=a,recipient=b,generation=9,withdrawal=digest('FUSE WithdrawalGateway',w),settlement=digest('FUSE SettlementController',s),reserve=digest('FUSE LPVault',r),deposit_batch=deposit,empty_deposit_batch=kh(enc('uint256[]','[]')),reward_leaf=leaf,lp_capacity=digest('FUSE LPShareVault',lp_capacity),lp_utilization=digest('FUSE LPIncentives',lp_utilization)),indent=2))
