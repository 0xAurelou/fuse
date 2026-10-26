package oracle

import (
	"encoding/json"
	"fmt"

	"fuse/engine/internal/engine"
)

type Level struct {
	Price  string `json:"px"`
	Size   string `json:"sz"`
	Orders int    `json:"n"`
}
type BBO struct {
	Coin   string   `json:"coin"`
	Time   int64    `json:"time"`
	Levels []*Level `json:"bbo"`
}

// ParseBBO accepts missing sides as market evidence, but rejects malformed or
// crossed quotes. Prices remain decimal strings and never feed barrier outcomes.
func ParseBBO(raw []byte) (BBO, error) {
	var e struct {
		Channel string `json:"channel"`
		Data    BBO    `json:"data"`
	}
	if err := json.Unmarshal(raw, &e); err != nil {
		return BBO{}, err
	}
	b := e.Data
	if e.Channel != "bbo" || b.Coin != "BTC" || b.Time <= 0 || len(b.Levels) != 2 {
		return b, fmt.Errorf("invalid BTC BBO envelope")
	}
	var prices [2]int64
	for i, l := range b.Levels {
		if l == nil {
			continue
		}
		p, err := engine.ParsePrice(l.Price)
		if err != nil || l.Orders < 0 {
			return b, fmt.Errorf("invalid BBO level")
		}
		prices[i] = p
		if _, err = engine.ParsePrice(l.Size); err != nil {
			return b, fmt.Errorf("invalid BBO size")
		}
	}
	if prices[0] > 0 && prices[1] > 0 && prices[0] > prices[1] {
		return b, fmt.Errorf("crossed BBO")
	}
	return b, nil
}
