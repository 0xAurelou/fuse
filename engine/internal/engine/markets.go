package engine

// BTC remains the default so historical commands and commitments stay unchanged.
func AssetName(asset string) string {
	if asset == "" {
		return "BTC"
	}
	return asset
}
func SupportedAsset(asset string) bool { return asset == "BTC" || asset == "ETH" || asset == "HYPE" }
func (p Policy) HasAsset(asset string) bool {
	asset = AssetName(asset)
	if asset == "BTC" {
		return true
	}
	_, ok := p.Markets[asset]
	return p.Product == SingleStage && ok
}
func (p Policy) AssetModel(asset string) Model {
	if AssetName(asset) == "BTC" {
		return p.Model
	}
	return p.Markets[asset]
}
func (p Policy) Assets() []string {
	assets := []string{"BTC"}
	for _, asset := range keys(p.Markets) {
		assets = append(assets, asset)
	}
	return assets
}
func (s State) AssetOracle(asset string) Oracle {
	if AssetName(asset) == "BTC" {
		return s.Oracle
	}
	if o := s.Oracles[asset]; o != nil {
		return *o
	}
	return Oracle{}
}
func (s *State) oraclePointer(asset string) *Oracle {
	if AssetName(asset) == "BTC" {
		return &s.Oracle
	}
	if s.Oracles == nil {
		s.Oracles = map[string]*Oracle{}
	}
	if s.Oracles[asset] == nil {
		s.Oracles[asset] = &Oracle{Sources: map[string]Feed{}, ReturnsBPS: []int64{}}
	}
	return s.Oracles[asset]
}
func (a *Account) head(asset string) string {
	if AssetName(asset) == "BTC" {
		return a.RunHead
	}
	return a.StageHeads[asset]
}
func (a *Account) setHead(asset, id string) {
	if AssetName(asset) == "BTC" {
		a.RunHead = id
		return
	}
	if id == "" {
		delete(a.StageHeads, asset)
		return
	}
	if a.StageHeads == nil {
		a.StageHeads = map[string]string{}
	}
	a.StageHeads[asset] = id
}
func (s State) OracleCommitment() string {
	if len(s.Oracles) == 0 {
		return s.Oracle.JournalHash
	}
	hashes := map[string]string{"BTC": s.Oracle.JournalHash}
	for asset, oracle := range s.Oracles {
		hashes[asset] = oracle.JournalHash
	}
	return Hash(hashes)
}
