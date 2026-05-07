# Bundled Default Images

These SVGs ship with the integration and are served at:

```
/morning_routine_frontend/images/<name>.svg
```

| File | Use |
|---|---|
| coffee.svg | Coffee / drink |
| breakfast.svg | Breakfast / cereal |
| teeth.svg | Brushing teeth |
| clothes.svg | Getting dressed (T-shirt) |
| shoes.svg | Shoes |
| backpack.svg | Schoolbag / leaving |
| shower.svg | Shower |
| done.svg | Routine complete |

All silhouettes are designed for the `mask` tint mode — solid black on transparent, dynamically tinted by the Lovelace card.

To add your own: drop PNG/SVG files into `config/www/morning/` on your HA host and reference them as `/local/morning/<file>.png`.

License: simple geometric primitives, original to this project, MIT.
