// Placeholder portfolio data for the dashboard's first version. There is no
// real brokerage/market-data integration in this project yet — connecting
// one (custody/clearing partner, live pricing feed, real order execution)
// is a substantially bigger project than "add a login page," so this
// returns the same representative figures shown in the homepage's
// portfolio-card mockup, per-request but otherwise static. Swap
// getDashboardData() for a real data source later; every page that
// consumes it only cares about this same shape.

function getDashboardData(user) {
  return {
    portfolioValue: 12450.82,
    todayChangeAbs: 184.20,
    todayChangePct: 1.51,
    chartPoints: [58, 61, 59, 64, 62, 68, 66, 71, 69, 75, 73, 78, 80],
    holdings: [
      { symbol: 'NVDA', name: 'NVIDIA Corp.', price: 201.30, changePct: 2.05 },
      { symbol: 'TSLA', name: 'Tesla Inc.', price: 256.90, changePct: 1.48 },
      { symbol: 'PLTR', name: 'Palantir Tech.', price: 168.44, changePct: -0.62 },
      { symbol: 'AMD', name: 'Advanced Micro', price: 142.18, changePct: 0.94 },
      { symbol: 'MSFT', name: 'Microsoft Corp.', price: 415.20, changePct: 0.72 },
    ],
    stablecoins: {
      USDT: 1240.00,
      USDC: 860.50,
    },
  };
}

module.exports = { getDashboardData };
