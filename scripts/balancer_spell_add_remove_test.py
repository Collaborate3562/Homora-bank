from brownie import accounts, interface, Contract
from brownie import (
    HomoraBank, ProxyOracle, BalancerPairOracle, SimpleOracle, BalancerSpellV1, WERC20
)


def almostEqual(a, b):
    thresh = 0.01
    return a <= b + thresh * abs(b) and a >= b - thresh * abs(b)


def setup_bank_hack(homora):
    donator = accounts[5]
    fake = accounts.at(homora.address, force=True)
    controller = interface.IComptroller(
        '0x3d5BC3c8d13dcB8bF317092d84783c2697AE9258')
    creth = interface.ICEtherEx('0xD06527D5e56A3495252A528C4987003b712860eE')
    creth.mint({'value': '90 ether', 'from': donator})
    creth.transfer(fake, creth.balanceOf(donator), {'from': donator})
    controller.enterMarkets([creth], {'from': fake})


def setup_transfer(asset, fro, to, amt):
    print(f'sending from {fro} {amt} {asset.name()} to {to}')
    asset.transfer(to, amt, {'from': fro})


def main():
    admin = accounts[0]

    alice = accounts[1]
    dai = interface.IERC20Ex('0x6B175474E89094C44Da98b954EedeAC495271d0F')
    weth = interface.IERC20Ex('0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2')

    lp = interface.IERC20Ex('0x8b6e6e7b5b3801fed2cafd4b22b8a16c2f2db21a')
    # pool is lp for balancer
    pool = interface.ICurvePool('0x8b6e6e7b5b3801fed2cafd4b22b8a16c2f2db21a')

    crdai = interface.ICErc20('0x92b767185fb3b04f881e3ac8e5b0662a027a1d9f')

    werc20 = WERC20.deploy({'from': admin})

    simple_oracle = SimpleOracle.deploy({'from': admin})
    simple_oracle.setETHPx([weth, dai], [5192296858534827628530496329220096,
                                         8887571220661441971398610676149])

    balancer_oracle = BalancerPairOracle.deploy(simple_oracle, {'from': alice})

    oracle = ProxyOracle.deploy({'from': admin})
    oracle.setWhitelistERC1155([werc20], True, {'from': admin})
    oracle.setOracles(
        [
            '0x6B175474E89094C44Da98b954EedeAC495271d0F',  # WETH
            '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',  # DAI
            '0x8b6e6e7b5b3801fed2cafd4b22b8a16c2f2db21a',  # lp
        ],
        [
            [simple_oracle, 10000, 10000, 10000],
            [simple_oracle, 10000, 10000, 10000],
            [balancer_oracle, 10000, 10000, 10000],
        ],
        {'from': admin},
    )

    homora = HomoraBank.deploy({'from': admin})
    homora.initialize(oracle, 1000, {'from': admin})  # 10% fee
    setup_bank_hack(homora)
    homora.addBank(dai, crdai, {'from': admin})

    # setup initial funds 10^5 DAI + 10^4 WETH to alice
    setup_transfer(dai, accounts.at(
        '0xc3d03e4f041fd4cd388c549ee2a29a9e5075882f', force=True), alice, 10**6 * 10**18)
    setup_transfer(weth, accounts.at(
        '0x397ff1542f962076d0bfe58ea045ffa2d347aca0', force=True), alice, 10**4 * 10**18)

    # setup initial funds 10^6 DAI + 10^4 WETH to homora bank
    setup_transfer(dai, accounts.at(
        '0xc3d03e4f041fd4cd388c549ee2a29a9e5075882f', force=True), homora, 10**6 * 10**6)
    setup_transfer(weth, accounts.at(
        '0x397ff1542f962076d0bfe58ea045ffa2d347aca0', force=True), homora, 10**4 * 10**18)

    # check alice's funds
    print(f'Alice weth balance {weth.balanceOf(alice)}')
    print(f'Alice dai balance {dai.balanceOf(alice)}')

    # Steal some LP from the staking pool
    lp.transfer(alice, 1*10**17, {'from': accounts.at(
        '0xafc2f2d803479a2af3a72022d54cc0901a0ec0d6', force=True)})
    lp.transfer(homora, 2*10**17, {'from': accounts.at(
        '0xafc2f2d803479a2af3a72022d54cc0901a0ec0d6', force=True)})

    # set approval
    dai.approve(homora, 2**256-1, {'from': alice})
    dai.approve(crdai, 2**256-1, {'from': alice})
    weth.approve(homora, 2**256-1, {'from': alice})
    lp.approve(homora, 2**256-1, {'from': alice})

    balancer_spell = BalancerSpellV1.deploy(
        homora, werc20, '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2', {'from': admin})
    # first time call to reduce gas
    balancer_spell.getPair(lp, {'from': admin})

    #####################################################################################
    print('=========================================================================')
    print('Case 1.')

    prevABal = dai.balanceOf(alice)
    prevBBal = weth.balanceOf(alice)
    prevLPBal = lp.balanceOf(alice)
    prevLPBal_bank = lp.balanceOf(homora)
    prevLPBal_werc20 = lp.balanceOf(werc20)

    prevARes = interface.IBalancerPool(lp).getBalance(dai)
    prevBRes = interface.IBalancerPool(lp).getBalance(weth)

    dai_amt = 40000 * 10**18
    weth_amt = 10 ** 18
    lp_amt = 1 * 10**16
    borrow_dai_amt = 1000 * 10**18
    borrow_weth_amt = 0

    # calculate slippage control
    total_dai_amt = dai_amt + borrow_dai_amt
    total_weth_amt = weth_amt + borrow_weth_amt
    dai_weight = 0.2
    weth_weight = 0.8

    ratio = (((prevARes + total_dai_amt) / prevARes) ** dai_weight) * \
        (((prevBRes + total_weth_amt) / prevBRes) ** weth_weight) - 1
    lp_desired = lp_amt + int(interface.IERC20(lp).totalSupply() * ratio * 0.995)
    print('lp desired', lp_desired)

    tx = homora.execute(
        0,
        balancer_spell,
        balancer_spell.addLiquidityWERC20.encode_input(
            lp,  # lp token
            [dai_amt,  # supply DAI
             weth_amt,   # supply WETH
             lp_amt,  # supply LP
             borrow_dai_amt,  # borrow DAI
             borrow_weth_amt,  # borrow WETH
             0,  # borrow LP tokens
             lp_desired]  # LP desired
        ),
        {'from': alice}
    )

    position_id = tx.return_value
    print('position_id', position_id)

    curABal = dai.balanceOf(alice)
    curBBal = weth.balanceOf(alice)
    curLPBal = lp.balanceOf(alice)
    curLPBal_bank = lp.balanceOf(homora)
    curLPBal_werc20 = lp.balanceOf(werc20)

    curARes = interface.IBalancerPool(lp).getBalance(dai)
    curBRes = interface.IBalancerPool(lp).getBalance(weth)

    print('spell lp balance', lp.balanceOf(balancer_spell))
    print('Alice delta A balance', curABal - prevABal)
    print('Alice delta B balance', curBBal - prevBBal)
    print('add liquidity gas', tx.gas_used)
    print('bank lp balance', curLPBal_bank)

    _, _, _, daiDebt, daiShare = homora.getBankInfo(dai)
    print('bank dai daiDebt', daiDebt)
    print('bank dai daiShare', daiShare)

    print('bank prev LP balance', prevLPBal_bank)
    print('bank cur LP balance', curLPBal_bank)

    print('werc20 prev LP balance', prevLPBal_werc20)
    print('werc20 cur LP balance', curLPBal_werc20)

    print('prev dai res', prevARes)
    print('cur dai res', curARes)

    print('prev weth res', prevBRes)
    print('cur weth res', curBRes)

    # alice
    assert almostEqual(curABal - prevABal, -dai_amt), 'incorrect DAI amt'
    assert almostEqual(curBBal - prevBBal, -weth_amt), 'incorrect WETH amt'
    assert curLPBal - prevLPBal == -lp_amt, 'incorrect LP amt'

    # spell
    assert dai.balanceOf(balancer_spell) == 0, 'non-zero spell DAI balance'
    assert weth.balanceOf(balancer_spell) == 0, 'non-zero spell WETH balance'
    assert lp.balanceOf(balancer_spell) == 0, 'non-zero spell LP balance'
    assert daiDebt == borrow_dai_amt

    # check balance and pool reserves
    assert almostEqual(curABal - prevABal - borrow_dai_amt, -
                       (curARes - prevARes)), 'not all DAI tokens go to LP pool'
    assert almostEqual(curBBal - prevBBal - borrow_weth_amt, -
                       (curBRes - prevBRes)), 'not all WETH tokens go to LP pool'

    #####################################################################################
    print('=========================================================================')
    print('Case 2.')

    # remove liquidity from the same position
    prevABal = dai.balanceOf(alice)
    prevBBal = weth.balanceOf(alice)
    prevETHBal = alice.balance()
    prevLPBal = lp.balanceOf(alice)
    prevLPBal_bank = lp.balanceOf(homora)
    prevLPBal_werc20 = lp.balanceOf(werc20)
    prevETHBal = alice.balance()

    prevARes = interface.IBalancerPool(lp).getBalance(dai)
    prevBRes = interface.IBalancerPool(lp).getBalance(weth)

    lp_take_amt = 2**256-1  # max
    lp_want = 1 * 10**15
    dai_repay = 2**256-1  # max
    weth_repay = 0

    real_dai_repay = homora.borrowBalanceStored(position_id, dai)
    _, _, _, real_lp_take_amt = homora.getPositionInfo(position_id)

    tx = homora.execute(
        position_id,
        balancer_spell,
        balancer_spell.removeLiquidityWERC20.encode_input(
            lp,  # LP token
            [lp_take_amt,  # take out LP tokens
             lp_want,   # withdraw LP tokens to wallet
             dai_repay,  # repay DAI
             weth_repay,   # repay WETH
             0,   # repay LP
             0,   # min DAI
             0],  # min WETH
        ),
        {'from': alice}
    )
    # return tx

    curABal = dai.balanceOf(alice)
    curBBal = weth.balanceOf(alice)
    curETHBal = alice.balance()
    curLPBal = lp.balanceOf(alice)
    curLPBal_bank = lp.balanceOf(homora)
    curLPBal_werc20 = lp.balanceOf(werc20)
    curETHBal = alice.balance()

    curARes = interface.IBalancerPool(lp).getBalance(dai)
    curBRes = interface.IBalancerPool(lp).getBalance(weth)

    print('spell lp balance', lp.balanceOf(balancer_spell))
    print('spell dai balance', dai.balanceOf(balancer_spell))
    print('spell weth balance', weth.balanceOf(balancer_spell))
    print('Alice delta A balance', curABal - prevABal)
    print('Alice delta B balance', curBBal - prevBBal)
    print('Alice delta ETH balance', curETHBal - prevETHBal)
    print('Alice delta LP balance', curLPBal - prevLPBal)
    print('remove liquidity gas', tx.gas_used)
    print('bank delta lp balance', curLPBal_bank - prevLPBal_bank)
    print('bank total lp balance', curLPBal_bank)

    _, _, _, daiDebt, daiShare = homora.getBankInfo(dai)
    print('bank dai totalDebt', daiDebt)
    print('bank dai totalShare', daiShare)

    print('LP want', lp_want)

    print('bank delta LP amount', curLPBal_bank - prevLPBal_bank)
    print('LP take amount', lp_take_amt)

    print('prev werc20 LP balance', prevLPBal_werc20)
    print('cur werc20 LP balance', curLPBal_werc20)

    print('real dai repay', real_dai_repay)

    # alice
    assert almostEqual(curBBal - prevBBal, 0), 'incorrect WETH amt'
    assert almostEqual(curLPBal - prevLPBal, lp_want), 'incorrect LP amt'

    # werc20
    assert almostEqual(curLPBal_werc20 - prevLPBal_werc20, -
                       real_lp_take_amt), 'incorrect werc20 LP amt'

    # spell
    assert dai.balanceOf(balancer_spell) == 0, 'non-zero spell DAI balance'
    assert weth.balanceOf(balancer_spell) == 0, 'non-zero spell WETH balance'
    assert lp.balanceOf(balancer_spell) == 0, 'non-zero spell LP balance'

    # check balance and pool reserves
    assert almostEqual(curABal - prevABal + real_dai_repay, -
                       (curARes - prevARes)), 'inconsistent DAI from withdraw'
    assert almostEqual(curBBal - prevBBal,
                       0), 'inconsistent WETH from withdraw'
    assert almostEqual(curETHBal - prevETHBal + weth_repay, -
                       (curBRes - prevBRes)), 'inconsistent ETH from withdraw'

    return tx
