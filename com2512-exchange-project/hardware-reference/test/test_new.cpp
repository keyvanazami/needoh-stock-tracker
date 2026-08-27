#include "../lib/bframe.h"
#include "../lib/framerx.h"
#include "../lib/book.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <vector>
static int pass=0, fail=0;
#define CHECK(c,...) do{ if(c) pass++; else { fail++; printf("  FAIL %d: ",__LINE__); printf(__VA_ARGS__); printf("\n"); } }while(0)

static std::vector<uint8_t> mk(uint8_t src,uint8_t dst,uint8_t type,const char*pl,uint8_t len){
  BFrame f{}; f.src=src; f.dst=dst; f.type=type; f.len=len; memcpy(f.payload,pl,len);
  uint8_t w[128]; size_t n=bf_encode(&f,w,sizeof w);
  return std::vector<uint8_t>(w,w+n);
}

static void t_rx(){
  printf("Frame receiver state machine\n");
  FrameRx rx; BFrame out{};
  auto fr = mk(0x21,0xFF,BF_T_QUOTE,"\x00\x01\x01\x2C\x00\x64\x01\x2D",8);

  // clean frame
  int got=0; for(uint8_t b: fr) got += rx.feed(b,&out);
  CHECK(got==1 && out.src==0x21 && out.len==8, "clean frame not received (got=%d)",got);
  printf("  clean frame accepted\n");

  // joining mid-frame then a good frame: must resync and get the second
  rx.reset(); got=0;
  for(size_t i=5;i<fr.size();i++) got += rx.feed(fr[i],&out);   // partial
  for(uint8_t b: fr) got += rx.feed(b,&out);                    // full
  CHECK(got==1, "mid-frame join did not resync to exactly one frame (got=%d)",got);
  printf("  joins mid-frame, resynchronises, receives the next one\n");

  // line noise before a frame
  rx.reset(); got=0;
  uint8_t noise[]={0x00,0xFF,0x13,0xAA,0x37,0x5C};
  for(uint8_t b: noise) got += rx.feed(b,&out);
  for(uint8_t b: fr) got += rx.feed(b,&out);
  CHECK(got==1, "noise then frame -> got %d",got);
  printf("  survives leading line noise\n");

  // back-to-back frames
  rx.reset(); got=0;
  for(int k=0;k<5;k++) for(uint8_t b: fr) got += rx.feed(b,&out);
  CHECK(got==5, "back-to-back: got %d want 5",got);
  printf("  5 back-to-back frames all received\n");

  // corrupted CRC must be rejected AND must not swallow the following frame
  rx.reset(); got=0;
  auto bad=fr; bad[bad.size()-1]^=0x40;
  for(uint8_t b: bad) got += rx.feed(b,&out);
  CHECK(got==0, "corrupt frame accepted");
  for(uint8_t b: fr) got += rx.feed(b,&out);
  CHECK(got==1, "did not recover after CRC error (got=%d)",got);
  CHECK(rx.crc_errors==1, "crc_errors=%u want 1",rx.crc_errors);
  printf("  CRC error rejected, receiver recovers for the next frame\n");

  // a bogus length byte must not hang the receiver
  rx.reset();
  uint8_t evil[]={BF_PREAMBLE,BF_PREAMBLE,BF_SFD,200,0x01,0x02,0x03};
  got=0; for(uint8_t b: evil) got += rx.feed(b,&out);
  CHECK(got==0 && rx.oversize==1, "oversize length not caught (oversize=%u)",rx.oversize);
  for(uint8_t b: fr) got += rx.feed(b,&out);
  CHECK(got==1, "no recovery after bogus length");
  printf("  impossible length field rejected, then recovers\n");

  // fuzz: random bytes must never produce a frame or crash
  rx.reset(); srand(11); got=0;
  for(int i=0;i<200000;i++) got += rx.feed((uint8_t)(rand()&0xFF),&out);
  printf("  fuzz: 200k random bytes -> %d spurious frames (CRC makes this rare, not impossible)\n",got);
  CHECK(got<=1, "too many spurious frames from noise: %d",got);
}

static void t_book(){
  printf("Order book matching\n");
  Book b; Fill f[8];

  // rest two bids, price priority
  b.submit({1,SIDE_BUY,1,100,10},f,8);
  b.submit({2,SIDE_BUY,2,102,5},f,8);
  CHECK(b.best_bid()==102 && b.bid_qty()==5, "best bid %u qty %u",b.best_bid(),b.bid_qty());
  printf("  higher bid takes priority: best bid %u x %u\n",b.best_bid(),b.bid_qty());

  // aggressive sell crosses the top bid only
  uint8_t n=b.submit({3,SIDE_SELL,3,101,5},f,8);
  CHECK(n==1 && f[0].px==102 && f[0].qty==5 && f[0].buy_firm==2 && f[0].sell_firm==3,
        "n=%u px=%u qty=%u",n,f[0].px,f[0].qty);
  printf("  sell 5 @101 fills 5 @102 against firm 2 (price improvement to resting order)\n");
  CHECK(b.best_bid()==100, "after fill best bid %u want 100",b.best_bid());

  // time priority at equal price
  Book c;
  c.submit({7,SIDE_BUY,1,100,3},f,8);
  c.submit({8,SIDE_BUY,2,100,3},f,8);
  n=c.submit({9,SIDE_SELL,3,100,6},f,8);
  CHECK(n==2 && f[0].buy_firm==7 && f[1].buy_firm==8, "time priority broken: %u then %u",f[0].buy_firm,f[1].buy_firm);
  printf("  equal prices fill in arrival order (firm 7 before firm 8)\n");

  // partial fill leaves remainder resting on the correct side
  Book d;
  d.submit({1,SIDE_SELL,1,50,10},f,8);
  n=d.submit({2,SIDE_BUY,2,50,4},f,8);
  CHECK(n==1 && f[0].qty==4 && d.ask_qty()==6, "partial fill wrong: qty=%u remaining=%u",f[0].qty,d.ask_qty());
  printf("  partial fill: 4 traded, 6 left resting\n");

  // no cross when spread is wide
  Book e;
  e.submit({1,SIDE_SELL,1,60,5},f,8);
  n=e.submit({2,SIDE_BUY,2,55,5},f,8);
  CHECK(n==0 && e.best_bid()==55 && e.best_ask()==60, "crossed when it should not");
  printf("  wide spread does not cross: %u / %u\n",e.best_bid(),e.best_ask());

  // book full must drop, never corrupt
  Book g;
  for(int i=0;i<20;i++) g.submit({(uint8_t)i,SIDE_BUY,(uint8_t)i,(uint16_t)(100+i),1},f,8);
  CHECK(g.nbid<=BOOK_DEPTH, "book overflowed: nbid=%u",g.nbid);
  bool sorted=true; for(uint8_t i=1;i<g.nbid;i++) if(g.bids[i-1].px < g.bids[i].px) sorted=false;
  CHECK(sorted, "book not sorted after overflow");
  printf("  20 orders into an 8-deep book: capped at %u, still sorted\n",g.nbid);
}

int main(){
  printf("=== New modules: receiver + matching engine ===\n\n");
  t_rx(); printf("\n"); t_book();
  printf("\n=== %d passed, %d failed ===\n",pass,fail);
  return fail?1:0;
}
