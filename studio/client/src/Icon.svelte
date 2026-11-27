<script lang="ts">
 let {name,size=20}:{name:string,size?:number}=$props()
 const icons:Record<string,string>={
 openwrt:'M3 13h18v7H3z M6 13V5 M18 13V5 M7 17h2 M16 17h2',qr:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h3v3h-3z M20 14v4h-3v3h4',converter:'M3 7h16l-4-4m4 4-4 4 M21 17H5l4 4m-4-4 4-4',templates:'M3 5h16v12H3z M7 20h15V9',linux:'M3 5h18v14H3z M6 9l3 3-3 3 M12 15h5',
 sun:'M12 4V2 M12 22v-2 M4 12H2 M22 12h-2 M4 4l2 2 M18 18l2 2 M4 20l2-2 M18 6l2-2 M16 12a4 4 0 11-8 0 4 4 0 018 0z',
 moon:'M20 15a8 8 0 01-11-11 9 9 0 1011 11z',copy:'M8 8h12v13H8z M15 5V3H4v13h2',launch:'M13 3h8v8 M21 3L10 14 M9 5H4v15h15v-6',check:'M4 12l5 5L20 6',
 sliders:'M3 6h7m4 0h7M3 17h11m4 0h3 M10 3v6 M16 14v6',info:'M21 12a9 9 0 11-18 0 9 9 0 0118 0z M12 11v5 M12 7v1',key:'M14 4a5 5 0 00-5 7L3 17v4h4v-3h3v-3l2-2a5 5 0 102-9z',
 windows:'M3 4h8v7H3z M13 4h8v7h-8z M3 13h8v7H3z M13 13h8v7h-8z',
 macos:'M3 4h18v13H3z M8 21h8 M12 17v4',
 tvos:'M2 5h20v13H2z M7 21h10 M8 2l4 3 4-3',
 ios:'M7 2h10a1 1 0 011 1v18a1 1 0 01-1 1H7a1 1 0 01-1-1V3a1 1 0 011-1z M10 5h4 M11 19h2',
 android:'M6 10h12v8H6z M6 8a6 6 0 0112 0z M8 3 6 1 M16 3l2-2 M3 11v5 M21 11v5 M9 18v4 M15 18v4',
 home:'M3 3h8v8H3z M14 3h7v5h-7z M14 11h7v10h-7z M3 14h8v7H3z',
 networks:'M4 6h6l4 12h6 M4 18h6l4-12h6 M17 3l3 3-3 3 M17 15l3 3-3 3',
 library:'M3 4h4v16H3z M9 4h4v16H9z M15 5l4-1 3 15-4 1z',
 devices:'M2 4h13v11H2z M5 18h7 M17 9h5v12h-5z',
 release:'M12 3v12 M7 8l5-5 5 5 M4 14v6h16v-6',
 spark:'M12 3l2.1 6.9L21 12l-6.9 2.1L12 21l-2.1-6.9L3 12l6.9-2.1z',
 arrow:'M5 12h14 M14 7l5 5-5 5'}
</script>
<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={icons[name]||icons.home}/></svg>
