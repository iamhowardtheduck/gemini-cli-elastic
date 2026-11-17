#!/bin/sh
# Assemble the full deck from the overview (o*), inference (i*) and load-test (p*) decks next to it.
# Order (fslides.config.js): overview up to the shared/data slides, the inference deck without its closing
# slide, the overview's dashboards to what-it-solves, the whole load-test deck, then the overview's get-started.
set -e
cd "$(dirname "$0")"
rm -f slides/o*.html slides/i*.html slides/p*.html
for f in ../deck/slides/[0-9]*.html;             do cp "$f" "slides/o$(basename "$f")"; done
for f in ../deck-inference/slides/[0-9]*.html;   do cp "$f" "slides/i$(basename "$f")"; done
for f in ../deck-performance/slides/[0-9]*.html; do cp "$f" "slides/p$(basename "$f")"; done
cp ../deck/slides/style/eweb.css ../deck/slides/style/eweb.js slides/style/
echo "synced $(ls slides/o*.html | wc -l) overview, $(ls slides/i*.html | wc -l) inference and $(ls slides/p*.html | wc -l) load-test slides"
# drop synced slides the config does not use (the overview's redaction/inference slides, the inference closing slide)
node -e "const c=require('./fslides.config.js'),fs=require('fs');for(const f of fs.readdirSync('slides'))if(/^[oip][0-9].*\.html$/.test(f)&&!c.slides.includes(f)){fs.unlinkSync('slides/'+f);console.log('dropped '+f)}"
