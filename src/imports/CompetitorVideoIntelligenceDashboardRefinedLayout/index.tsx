import svgPaths from "./svg-siexpc9d1x";

function Container2() {
  return (
    <div className="relative shrink-0 size-[16.667px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="16.6667" preserveAspectRatio="none" viewBox="0 0 16.6667 16.6667" width="16.6667">
        <g id="Container">
          <path d={svgPaths.p367d180} fill="#C0C1FF" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Background() {
  return (
    <div className="bg-[#31353f] content-stretch flex items-center justify-center relative rounded-[8px] shrink-0 size-[32px]" data-name="Background">
      <Container2 />
      <div className="absolute bg-[#c0c1ff] right-[4px] rounded-[9999px] size-[8px] top-[4px]" data-name="Background" />
      <div className="absolute bg-[#c0c1ff] right-[4px] rounded-[9999px] size-[8px] top-[4px]" data-name="Background" />
    </div>
  );
}

function Container4() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0 w-full" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#dfe2ef] text-[18px] tracking-[-0.45px] whitespace-nowrap">
        <p>
          <span className="leading-[18px]">TW-DASH</span>
        </p>
      </div>
    </div>
  );
}

function Container5() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0 w-full" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[11px] tracking-[0.55px] uppercase whitespace-nowrap">
        <p className="leading-[14px]">OUTPERFORM STUDIO</p>
      </div>
    </div>
  );
}

function Container3() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <Container4 />
      <Container5 />
    </div>
  );
}

function Container1() {
  return (
    <div className="relative shrink-0" data-name="Container">
      <div className="bg-clip-padding border-0 border-[transparent] border-solid content-stretch flex gap-[10px] items-center relative size-full">
        <Background />
        <Container3 />
      </div>
    </div>
  );
}

function Container6() {
  return (
    <div className="h-[9px] relative shrink-0 w-[9.3px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="9" preserveAspectRatio="none" viewBox="0 0 9.3 9" width="9.3">
        <g id="Container">
          <path d={svgPaths.p2d6f5ae0} fill="#C7C4D7" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Button() {
  return (
    <div className="bg-[#262a34] relative rounded-[8px] shrink-0" data-name="Button">
      <div className="bg-clip-padding border-0 border-[transparent] border-solid content-stretch flex items-center justify-center p-[6px] relative size-full">
        <Container6 />
      </div>
    </div>
  );
}

function HorizontalBorder() {
  return (
    <div className="h-[64px] relative shrink-0 w-full" data-name="HorizontalBorder">
      <div aria-hidden className="absolute border-[rgba(49,53,63,0.2)] border-b border-solid inset-0 pointer-events-none" />
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex items-center justify-between pb-px px-[16px] relative size-full">
          <Container1 />
          <Button />
        </div>
      </div>
    </div>
  );
}

function Container9() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0 w-full" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[11px] tracking-[0.66px] uppercase whitespace-nowrap">
        <p className="leading-[14px]">WORKSPACE</p>
      </div>
    </div>
  );
}

function Container10() {
  return (
    <div className="content-stretch flex flex-col items-start max-w-[160px] overflow-clip relative shrink-0 w-full" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#dfe2ef] text-[12px] whitespace-nowrap">
        <p className="leading-[16px]">Consumer Tech Competitors</p>
      </div>
    </div>
  );
}

function Container8() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <Container9 />
      <Container10 />
    </div>
  );
}

function Container11() {
  return (
    <div className="h-[11.933px] relative shrink-0 w-[6px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="11.9333" preserveAspectRatio="none" viewBox="0 0 6 11.9333" width="6">
        <g id="Container">
          <path d={svgPaths.p92c2900} fill="#C7C4D7" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Button1() {
  return (
    <div className="content-stretch flex flex-col items-center justify-center pb-[10px] pt-[4px] px-[4px] relative rounded-[4px] shrink-0" data-name="Button">
      <Container11 />
    </div>
  );
}

function Background1() {
  return (
    <div className="bg-[#262a34] relative rounded-[8px] shrink-0 w-full" data-name="Background">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex items-center justify-between p-[8px] relative size-full">
          <Container8 />
          <Button1 />
        </div>
      </div>
    </div>
  );
}

function Container7() {
  return (
    <div className="relative shrink-0 w-full" data-name="Container">
      <div className="content-stretch flex flex-col items-start px-[12px] py-[8px] relative size-full">
        <Background1 />
      </div>
    </div>
  );
}

function Container12() {
  return (
    <div className="relative shrink-0 w-full" data-name="Container">
      <div className="content-stretch flex flex-col items-start pb-[7px] pt-[15px] px-[16px] relative size-full">
        <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#908fa0] text-[11px] tracking-[0.55px] uppercase w-full">
          <p className="leading-[14px]">{`TELEMETRY & ANALYSIS`}</p>
        </div>
      </div>
    </div>
  );
}

function Container13() {
  return (
    <div className="h-[13.333px] relative shrink-0 w-[16.668px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="13.3333" preserveAspectRatio="none" viewBox="0 0 16.6681 13.3333" width="16.6681">
        <g id="Container">
          <path d={svgPaths.p350ec980} fill="#0D0096" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container14() {
  return (
    <div className="content-stretch flex flex-col items-start overflow-clip relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#0d0096] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">Overperformance</p>
      </div>
    </div>
  );
}

function Background2() {
  return (
    <div className="bg-[#a40217] content-stretch flex flex-col items-start px-[6px] py-[2px] relative rounded-[9999px] shrink-0" data-name="Background">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#ffaea8] text-[11px] tracking-[0.66px] whitespace-nowrap">
        <p className="leading-[14px]">14</p>
      </div>
    </div>
  );
}

function Margin() {
  return (
    <div className="flex-[1_0_0] min-w-[24.329999923706055px] relative" data-name="Margin">
      <div className="flex flex-col items-end min-w-[inherit] size-full">
        <div className="content-stretch flex flex-col items-end min-w-[inherit] pl-[82px] relative size-full">
          <Background2 />
        </div>
      </div>
    </div>
  );
}

function Link() {
  return (
    <div className="bg-[#8083ff] relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container13 />
          <Container14 />
          <Margin />
        </div>
      </div>
    </div>
  );
}

function Container15() {
  return (
    <div className="h-[10px] relative shrink-0 w-[20px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="10" preserveAspectRatio="none" viewBox="0 0 20 10" width="20">
        <g id="Container">
          <path d={svgPaths.p279daa80} fill="#C7C4D7" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container16() {
  return (
    <div className="content-stretch flex flex-col items-start overflow-clip relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">Competitor Roster</p>
      </div>
    </div>
  );
}

function Link1() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container15 />
          <Container16 />
        </div>
      </div>
    </div>
  );
}

function Container17() {
  return (
    <div className="h-[10.833px] relative shrink-0 w-[16.667px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="10.8333" preserveAspectRatio="none" viewBox="0 0 16.6667 10.8333" width="16.6667">
        <g id="Container">
          <path d={svgPaths.p617b400} fill="#C7C4D7" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container18() {
  return (
    <div className="content-stretch flex flex-col items-start overflow-clip relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">{`Trend & Velocity`}</p>
      </div>
    </div>
  );
}

function Link2() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container17 />
          <Container18 />
        </div>
      </div>
    </div>
  );
}

function Container19() {
  return (
    <div className="relative shrink-0 size-[15px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="15" preserveAspectRatio="none" viewBox="0 0 15 15" width="15">
        <g id="Container">
          <path d={svgPaths.p1d75e100} fill="#C7C4D7" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container20() {
  return (
    <div className="content-stretch flex flex-col items-start overflow-clip relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">Format Matrix</p>
      </div>
    </div>
  );
}

function Link3() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container19 />
          <Container20 />
        </div>
      </div>
    </div>
  );
}

function Container21() {
  return (
    <div className="h-[13.333px] relative shrink-0 w-[16.667px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="13.3333" preserveAspectRatio="none" viewBox="0 0 16.6667 13.3333" width="16.6667">
        <g id="Container">
          <path d={svgPaths.p110e1200} fill="#C7C4D7" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container22() {
  return (
    <div className="content-stretch flex flex-col items-start overflow-clip relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">Comparison</p>
      </div>
    </div>
  );
}

function Link4() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container21 />
          <Container22 />
        </div>
      </div>
    </div>
  );
}

function Container23() {
  return (
    <div className="h-[16.708px] relative shrink-0 w-[16.667px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="16.7083" preserveAspectRatio="none" viewBox="0 0 16.6667 16.7083" width="16.6667">
        <g id="Container">
          <path d={svgPaths.p1dcf6b00} fill="#C7C4D7" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container24() {
  return (
    <div className="content-stretch flex flex-col items-start overflow-clip relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">Alert Rules</p>
      </div>
    </div>
  );
}

function Link5() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container23 />
          <Container24 />
        </div>
      </div>
    </div>
  );
}

function Nav() {
  return (
    <div className="relative shrink-0 w-full" data-name="Nav">
      <div className="content-stretch flex flex-col gap-[4px] items-start px-[8px] relative size-full">
        <Link />
        <Link1 />
        <Link2 />
        <Link3 />
        <Link4 />
        <Link5 />
      </div>
    </div>
  );
}

function Container26() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#908fa0] text-[11px] tracking-[0.55px] uppercase whitespace-nowrap">
        <p className="leading-[14px]">SAVED COHORTS</p>
      </div>
    </div>
  );
}

function Button2() {
  return (
    <div className="relative shrink-0 size-[8.167px]" data-name="Button">
      <svg className="absolute block inset-0 size-full" fill="none" height="8.16667" preserveAspectRatio="none" viewBox="0 0 8.16667 8.16667" width="8.16667">
        <g id="Button">
          <path d={svgPaths.p10ad69c0} fill="#C0C1FF" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container25() {
  return (
    <div className="relative shrink-0 w-full" data-name="Container">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex items-center justify-between pb-[4px] pt-[16px] px-[16px] relative size-full">
          <Container26 />
          <Button2 />
        </div>
      </div>
    </div>
  );
}

function Container27() {
  return (
    <div className="h-[12px] relative shrink-0 w-[15px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="12" preserveAspectRatio="none" viewBox="0 0 15 12" width="15">
        <g id="Container">
          <path d={svgPaths.p168bfe00} fill="#C0C1FF" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container28() {
  return (
    <div className="content-stretch flex flex-[1_0_0] flex-col items-start min-w-px overflow-clip relative" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] w-full">
        <p className="leading-[20px]">Tech Giants</p>
      </div>
    </div>
  );
}

function Container29() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#908fa0] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">6</p>
      </div>
    </div>
  );
}

function Link6() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container27 />
          <Container28 />
          <Container29 />
        </div>
      </div>
    </div>
  );
}

function Container30() {
  return (
    <div className="h-[9px] relative shrink-0 w-[15px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="9" preserveAspectRatio="none" viewBox="0 0 15 9" width="15">
        <g id="Container">
          <path d={svgPaths.p304ae610} fill="#FFB3AD" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container31() {
  return (
    <div className="content-stretch flex flex-[1_0_0] flex-col items-start min-w-px overflow-clip relative" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] w-full">
        <p className="leading-[20px]">{`EDC & Desk`}</p>
      </div>
    </div>
  );
}

function Container32() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#908fa0] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">8</p>
      </div>
    </div>
  );
}

function Link7() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container30 />
          <Container31 />
          <Container32 />
        </div>
      </div>
    </div>
  );
}

function Container33() {
  return (
    <div className="h-[13.5px] relative shrink-0 w-[15px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="13.5" preserveAspectRatio="none" viewBox="0 0 15 13.5" width="15">
        <g id="Container">
          <path d={svgPaths.p211d8500} fill="#FFB0CD" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container34() {
  return (
    <div className="content-stretch flex flex-[1_0_0] flex-col items-start min-w-px overflow-clip relative" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[14px] tracking-[-0.07px] w-full">
        <p className="leading-[20px]">Camera Labs</p>
      </div>
    </div>
  );
}

function Container35() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#908fa0] text-[14px] tracking-[-0.07px] whitespace-nowrap">
        <p className="leading-[20px]">5</p>
      </div>
    </div>
  );
}

function Link8() {
  return (
    <div className="relative rounded-[8px] shrink-0 w-full" data-name="Link">
      <div className="flex flex-row items-center size-full">
        <div className="content-stretch flex gap-[12px] items-center px-[12px] py-[8px] relative size-full">
          <Container33 />
          <Container34 />
          <Container35 />
        </div>
      </div>
    </div>
  );
}

function Nav1() {
  return (
    <div className="relative shrink-0 w-full" data-name="Nav">
      <div className="content-stretch flex flex-col gap-[4px] items-start px-[8px] relative size-full">
        <Link6 />
        <Link7 />
        <Link8 />
      </div>
    </div>
  );
}

function Container() {
  return (
    <div className="content-stretch flex flex-[1_0_0] flex-col items-start min-h-px overflow-x-clip overflow-y-auto relative w-full" data-name="Container">
      <HorizontalBorder />
      <Container7 />
      <Container12 />
      <Nav />
      <Container25 />
      <Nav1 />
    </div>
  );
}

function Container37() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#c7c4d7] text-[11px] tracking-[0.66px] uppercase whitespace-nowrap">
        <p className="leading-[14px]">API QUOTA</p>
      </div>
    </div>
  );
}

function Container38() {
  return (
    <div className="content-stretch flex flex-col items-start relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Bold',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#dfe2ef] text-[12px] tracking-[-0.12px] whitespace-nowrap">
        <p className="leading-[16px]">84%</p>
      </div>
    </div>
  );
}

function Container36() {
  return (
    <div className="content-stretch flex items-center justify-between relative shrink-0 w-full" data-name="Container">
      <Container37 />
      <Container38 />
    </div>
  );
}

function Background4() {
  return (
    <div className="bg-[#31353f] h-[6px] overflow-clip relative rounded-[9999px] shrink-0 w-full" data-name="Background">
      <div className="absolute bg-[#c0c1ff] inset-[0_16%_0_0]" data-name="Background" />
    </div>
  );
}

function Container40() {
  return (
    <div className="content-stretch flex flex-col items-start overflow-clip relative shrink-0" data-name="Container">
      <div className="[word-break:break-word] flex flex-col font-['Liberation_Serif:Regular',sans-serif] justify-center leading-[0] not-italic relative shrink-0 text-[#908fa0] text-[12px] whitespace-nowrap">
        <p className="leading-[16px]">{`YT & IG Graph`}</p>
      </div>
    </div>
  );
}

function Container41() {
  return (
    <div className="h-[9.333px] relative shrink-0 w-[11.668px]" data-name="Container">
      <svg className="absolute block inset-0 size-full" fill="none" height="9.33333" preserveAspectRatio="none" viewBox="0 0 11.6676 9.33333" width="11.6676">
        <g id="Container">
          <path d={svgPaths.p1cccc530} fill="#908FA0" id="Icon" />
        </g>
      </svg>
    </div>
  );
}

function Container39() {
  return (
    <div className="content-stretch flex items-center justify-between relative shrink-0 w-full" data-name="Container">
      <Container40 />
      <Container41 />
    </div>
  );
}

function Background3() {
  return (
    <div className="bg-[#1c1f29] relative rounded-[12px] shrink-0 w-full" data-name="Background">
      <div className="content-stretch flex flex-col gap-[4px] items-start p-[12px] relative size-full">
        <Container36 />
        <Background4 />
        <Container39 />
      </div>
    </div>
  );
}

function Margin1() {
  return (
    <div className="relative shrink-0 w-full" data-name="Margin">
      <div className="content-stretch flex flex-col items-start p-[8px] relative size-full">
        <Background3 />
      </div>
    </div>
  );
}

function Aside() {
  return (
    <div className="bg-[#181b25] content-stretch drop-shadow-[0px_1px_4px_rgba(0,0,0,0.04)] flex flex-col h-[1024px] items-start justify-between relative shrink-0 w-[288px]" data-name="Aside">
      <Container />
      <Margin1 />
    </div>
  );
}

export default function CompetitorVideoIntelligenceDashboardRefinedLayout() {
  return (
    <div className="content-stretch flex flex-col items-start relative size-full" style={{ backgroundImage: "linear-gradient(90deg, rgb(15, 19, 28) 0%, rgb(15, 19, 28) 100%), linear-gradient(90deg, rgb(255, 255, 255) 0%, rgb(255, 255, 255) 100%)" }} data-name="Competitor Video Intelligence Dashboard (Refined Layout)">
      <Aside />
    </div>
  );
}