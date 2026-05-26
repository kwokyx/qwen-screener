import client from './client'

/**
 * 运行回测
 * @param {object} req
 * @param {string} req.name
 * @param {Array<{field:string, op:string, value:any}>} req.conditions
 * @param {string} req.start_date  YYYY-MM-DD
 * @param {string} req.end_date    YYYY-MM-DD
 * @param {number} [req.holdings_count]
 * @param {'monthly'|'weekly'|'daily'} [req.rebalance]
 * @param {number} [req.initial_capital]
 * @param {number} [req.transaction_cost]
 * @param {number|null} [req.stop_loss]
 * @returns {Promise<object>} BacktestResponse
 */
export async function runBacktest(req) {
  const { data } = await client.post('/strategy/backtest', req)
  return data
}
