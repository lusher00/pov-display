# povd-hub quote package

Generated 2026-10-24 from the KiCad 10 project as saved (schematic with LCSC fields, board after F8).

## Files

| File | Use |
|---|---|
| povd-hub_gerbers_QUOTE_ONLY.zip | Gerbers + Excellon drill for pricing. The board is placed but NOT routed: no traces or pours. Price is the same as the routed board; do not order fabrication from these. |
| povd-hub_BOM_JLC.csv | JLC assembly BOM: 103 parts JLC places (top side, SMT). |
| povd-hub_CPL_JLC.csv | JLC position file for those 103 parts, top side only. Coordinates match the Gerbers. |
| povd-hub_hand_solder.csv | Parts you fit yourself: large parts on the bottom (DNP in the schematic) and the through-hole parts. |

## PCB settings for the quote

- 84 x 70 mm, 4 layers, 1.6 mm, ENIG, quantity 5.
- Copper: get one price at 1 oz outer / 0.5 oz inner and one at 2 oz outer. The design notes call for 2 oz outer for the 15 A rail; it costs noticeably more on 4 layers.
- Via plating and minimum track/space at the standard JLC values.

## Assembly settings

- Economic PCBA, top side only. Parts with "dnp" and the through-hole parts are not in the BOM/CPL.
- 15 lines carry an LCSC number (all ICs, FETs, connectors, ESD, Schottky, Keystone 5015, 10k). The passives (resistors, ceramics, LED) are left for the JLC BOM tool to match by value and package; pick basic parts where offered. The odd values (95.3k, 22.1k, 24.9k, 1.91k, 11k, 6.8 nF, 12 nF) will be extended parts.
- Check rotations in the JLC placement preview, especially SOT-23-5/6, TSSOP-20, VQFN-20, TDSON-8 and the connectors.

## Not decided yet (changes cost very little, check before ordering)

- Board size and standoff positions on top of the hub.
- S3-Zero footprint row spacing and pin order against the Waveshare drawing.
- LM5145 compensation and current limit in the TI Quickstart Calculator.
