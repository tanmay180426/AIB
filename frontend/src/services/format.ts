/** BRL formatting for the reference warehouse and BRL-compatible models. */
export const fmtMoney = (n: number) =>
  `R$ ${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
